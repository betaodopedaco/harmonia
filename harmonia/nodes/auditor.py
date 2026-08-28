from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime
from typing import Any

from harmonia.graph.state import (
    HarmoniaState,
    make_fundamento,
    make_etapa_plano,
    make_acao_proposta,
)
from harmonia.integrations.opencode_client import OpenCodeClient, OpenCodeConfig


AUDITOR_PROMPT = """
Você é o Auditor do Harmonia. Sua tarefa é escanear o repositório atual e identificar
tudo que precisa ser feito: TODOs, testes faltando, bugs óbvios, código incompleto,
deuda técnica, documentação faltando, etc.

Escaneie o repositório inteiro (use ferramentas de leitura de arquivo, busca, listagem).
Foque em:
1. Arquivos com TODO/FIXME/HACK/XXX nos comentários
2. Funções/classes com "pass" ou "raise NotImplementedError"
3. Testes faltando (arquivos de teste ausentes para módulos principais)
4. Código duplicado óbvio
5. Tratamento de erro ausente (try/except faltando)
6. Logs/prints de debug que deveriam ser removidos
7. Configurações hardcoded que deveriam ser variáveis de ambiente
8. Segurança: secrets hardcoded, SQL injection risks, etc.
9. Performance: loops desnecessários, queries N+1, etc.
9. Documentação: funções públicas sem docstring, README desatualizado

Para cada item encontrado, crie uma ação proposta com:
- tipo: categoria da ação (ex: "refatorar", "criar_teste", "corrigir_bug", "documentar", "remover_debug", "mover_config", "corrigir_seguranca", "otimizar")
- descricao: descrição clara e acionável do que fazer
- parametros: dict com detalhes (arquivo, linha, contexto)
- risco: "baixo" | "medio" | "alto" (baixo = refatoração interna/testes; medio = refatoração visível/config; alto = segurança/produção/dados)
- raciocinio: por que isso precisa ser feito
- impacto_estimado: descrição do impacto se não for feito
- rollback: como desfazer se der errado
- reversivel: true/false

Retorne APENAS um JSON válido com esta estrutura:
{
  "fundamentos": [
    {"id": "f1", "descricao": "Descrição do fundamento", "prioridade": 1}
  ],
  "etapas": [
    {
      "id": "e1",
      "descricao": "Descrição da etapa",
      "fundamentos_ids": ["f1"],
      "acoes_propostas": [
        {
          "tipo": "criar_teste",
          "descricao": "Criar testes unitários para módulo X",
          "parametros": {"arquivo": "src/modulo.py", "funcao": "funcao_x"},
          "raciocinio": "Módulo X não tem testes e é crítico",
          "impacto_estimado": "Sem testes, regressões não são detectadas",
          "rollback": "Remover arquivo de teste criado",
          "reversivel": true,
          "risco": "baixo"
        }
      ]
    }
  ]
}

IMPORTANTE: Retorne APENAS o JSON, sem texto adicional, sem markdown, sem explicações.
"""


async def _get_repo_context() -> str:
    """Coleta contexto do repositório: estrutura, arquivos principais, etc."""
    context_parts = []
    
    # Estrutura de diretórios
    try:
        result = subprocess.run(
            ["find", "/workspaces/harmonia", "-type", "f", "-name", "*.py", 
             "!", "-path", "*/node_modules/*", "!", "-path", "*/.git/*",
             "!", "-path", "*/__pycache__/*", "!", "-path", "*/.venv/*"],
            capture_output=True, text=True, timeout=30, cwd="/workspaces/harmonia"
        )
        py_files = result.stdout.strip().split('\n')[:50]
        context_parts.append(f"Arquivos Python ({len(py_files)} encontrados):\n" + "\n".join(py_files))
    except Exception:
        pass
    
    # Git status
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=10, cwd="/workspaces/harmonia"
        )
        if result.stdout.strip():
            context_parts.append(f"Git status:\n{result.stdout}")
    except Exception:
        pass
    
    # Últimos commits
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, timeout=10, cwd="/workspaces/harmonia"
        )
        context_parts.append(f"Últimos commits:\n{result.stdout}")
    except Exception:
        pass
    
    return "\n\n".join(context_parts)


async def _run_auditor_prompt(opencode_client: OpenCodeClient, prompt: str) -> str:
    """Executa o prompt do auditor no OpenCode e retorna a resposta."""
    session_title = f"auditor-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    resultado = await opencode_client.execute(
        prompt=prompt,
        session_title=session_title,
        model="nvidia/nemotron-3-ultra",
    )
    
    if not resultado.success:
        raise RuntimeError(f"Auditor falhou: {resultado.error}")
    
    # Extrair texto da resposta
    output_parts = []
    for part in resultado.messages:
        if isinstance(part, dict) and part.get("type") == "text":
            output_parts.append(part.get("text", ""))
        elif isinstance(part, str):
            output_parts.append(part)
    
    return "\n".join(output_parts)


def _parse_auditor_response(response: str) -> dict:
    """Extrai e valida o JSON da resposta do auditor."""
    # Tentar extrair JSON da resposta
    response = response.strip()
    
    # Se tiver markdown code block, extrair
    if "```json" in response:
        start = response.find("```json") + 7
        end = response.find("```", start)
        response = response[start:end].strip()
    elif "```" in response:
        start = response.find("```") + 3
        end = response.find("```", start)
        response = response[start:end].strip()
    
    # Tentar parsear JSON
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        # Tentar encontrar JSON válido na resposta
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(response[start:end])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Resposta do auditor não é JSON válido: {e}")


def _converter_plano_para_estado(plano_json: dict, state: HarmoniaState) -> HarmoniaState:
    """Converte o JSON do auditor para o estado do Harmonia."""
    novo_state = dict(state)
    
    # Fundamentos
    fundamentos = []
    for f in plano_json.get("fundamentos", []):
        fundamentos.append(make_fundamento(
            id=f.get("id", ""),
            descricao=f.get("descricao", ""),
            prioridade=f.get("prioridade", 0),
        ))
    novo_state["fundamentos"] = fundamentos
    
    # Etapas e ações
    etapas = []
    acoes_pendentes = []
    
    for i, e in enumerate(plano_json.get("etapas", [])):
        fundamentos_ids = e.get("fundamentos_ids", [])
        
        acoes_etapa = []
        for acao_data in e.get("acoes_propostas", []):
            acao = make_acao_proposta(
                tipo=acao_data.get("tipo", ""),
                descricao=acao_data.get("descricao", ""),
                parametros=acao_data.get("parametros", {}),
                risco=acao_data.get("risco", "baixo"),
                raciocinio=acao_data.get("raciocinio", ""),
                impacto_estimado=acao_data.get("impacto_estimado", ""),
                rollback=acao_data.get("rollback"),
                reversivel=acao_data.get("reversivel", True),
                max_tentativas=3,
            )
            acoes_etapa.append(acao)
            acoes_pendentes.append(acao)
        
        etapa = make_etapa_plano(
            id=e.get("id", f"etapa_{i}"),
            descricao=e.get("descricao", f"Etapa {i+1}"),
            fundamentos_ids=fundamentos_ids,
            acoes_propostas=acoes_etapa,
            ordem=i,
        )
        etapas.append(etapa)
    
    novo_state["etapas"] = etapas
    novo_state["acoes_pendentes"] = acoes_pendentes
    
    return novo_state


async def auditor(state: HarmoniaState) -> dict:
    """
    Nó Auditor: escaneia o repositório via OpenCode e gera plano de ações.
    """
    print("[AUDITOR] Iniciando auditoria do repositório...")
    
    # Coletar contexto do repo
    repo_context = await _get_repo_context()
    
    # Prompt completo
    prompt = AUDITOR_PROMPT + f"\n\nContexto do repositório:\n{repo_context}"
    
    # Criar cliente OpenCode
    config = OpenCodeConfig(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    client = OpenCodeClient(config)
    await client.connect()
    
    try:
        # Executar auditor
        resposta = await _run_auditor_prompt(client, prompt)
        print(f"[AUDITOR] Resposta recebida ({len(resposta)} chars)")
        
        # Parsear resposta
        plano_json = _parse_auditor_response(resposta)
        print(f"[AUDITOR] Plano parseado: {len(plano_json.get('etapas', []))} etapas, "
              f"{sum(len(e.get('acoes_propostas', [])) for e in plano_json.get('etapas', []))} ações")
        
        # Converter para estado
        novo_state = _converter_plano_para_estado(plano_json, state)
        
        # Log
        total_acoes = len(novo_state.get("acoes_pendentes", []))
        print(f"[AUDITOR] Plano gerado: {len(novo_state.get('fundamentos', []))} fundamentos, "
              f"{len(novo_state.get('etapas', []))} etapas, {total_acoes} ações")
        
        return {
            "fundamentos": novo_state["fundamentos"],
            "etapas": novo_state["etapas"],
            "acoes_pendentes": novo_state["acoes_pendentes"],
            "metadata": {
                **state.get("metadata", {}),
                "auditoria_gerada_em": datetime.now().isoformat(),
                "total_acoes_geradas": total_acoes,
            }
        }
        
    except Exception as e:
        print(f"[AUDITOR] Erro: {e}")
        # Em caso de erro, retorna estado sem alterações mas com erro no metadata
        return {
            "metadata": {
                **state.get("metadata", {}),
                "auditoria_erro": str(e),
                "auditoria_gerada_em": datetime.now().isoformat(),
            }
        }
    finally:
        await client.close()


# Função wrapper para compatibilidade com o grafo
async def auditor_node(state: HarmoniaState) -> dict:
    """Wrapper assíncrono para o nó auditor."""
    return await auditor(state)