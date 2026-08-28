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


# Prompt SIMPLIFICADO e DIRETO - foco em coisas concretas e acionáveis
AUDITOR_PROMPT = """
Scan this repository and find CONCRETE, ACTIONABLE issues. Return ONLY valid JSON.

Focus on THESE specific patterns (use grep/read tools):
1. TODO/FIXME/HACK/XXX comments in .py files
2. Functions with "pass" or "raise NotImplementedError" as only body
3. Missing tests: .py files in harmonia/ without corresponding test_*.py in tests/
4. Hardcoded secrets/tokens (grep for "ghp_", "nvapi_", "sk-", "api_key")
5. print() statements that should be logging
6. Bare "except:" or "except Exception:" without specific handling

Return ONLY this JSON structure:
{
  "fundamentos": [{"id": "f1", "descricao": "Brief reason", "prioridade": 1}],
  "etapas": [{
    "id": "e1",
    "descricao": "Brief stage name",
    "fundamentos_ids": ["f1"],
    "acoes_propostas": [{
      "tipo": "corrigir_bug|criar_teste|remover_debug|corrigir_seguranca|refatorar|documentar",
      "descricao": "Specific action: what file, what to do",
      "parametros": {"arquivo": "path/to/file.py", "linha": 123},
      "raciocinio": "Why this matters",
      "impacto_estimado": "Impact if not fixed",
      "rollback": "How to undo",
      "reversivel": true,
      "risco": "baixo|medio|alto"
    }]
  }]
}

ONLY JSON. No markdown. No explanations.
"""

async def _get_repo_context() -> str:
    """Contexto rápido do repo - apenas essenciais."""
    context_parts = []
    
    # Apenas arquivos .py principais (exclui node_modules, .git, __pycache__, .venv, baileys_server)
    try:
        result = subprocess.run(
            ["find", "/workspaces/harmonia", "-type", "f", "-name", "*.py",
             "!", "-path", "*/node_modules/*", "!", "-path", "*/.git/*",
             "!", "-path", "*/__pycache__/*", "!", "-path", "*/.venv/*",
             "!", "-path", "*/baileys_server/*"],
            capture_output=True, text=True, timeout=15, cwd="/workspaces/harmonia"
        )
        py_files = [f for f in result.stdout.strip().split('\n') if f and not f.endswith('.pyc')]
        context_parts.append(f"Python files ({len(py_files)}):\n" + "\n".join(py_files[:30]))
    except Exception:
        pass
    
    # Git status rápido
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=5, cwd="/workspaces/harmonia"
        )
        if result.stdout.strip():
            context_parts.append(f"Git changes:\n{result.stdout.strip()}")
    except Exception:
        pass
    
    return "\n\n".join(context_parts)[:3000]  # Limita contexto


async def _run_auditor_prompt(opencode_client: OpenCodeClient, prompt: str) -> str:
    """Executa prompt do auditor com timeout reduzido."""
    session_title = f"auditor-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    resultado = await asyncio.wait_for(
        opencode_client.execute(
            prompt=prompt,
            session_title=session_title,
            model="nvidia/nemotron-3-ultra",
            timeout=120.0,  # 2 min max
        ),
        timeout=130.0
    )
    
    if not resultado.success:
        raise RuntimeError(f"Auditor falhou: {resultado.error}")
    
    # Extrair texto - resultado.messages pode ser lista de dicts ou strings
    output_parts = []
    for part in resultado.messages:
        if isinstance(part, dict):
            if part.get("type") == "text":
                output_parts.append(part.get("text", ""))
            elif part.get("type") == "tool":
                output_parts.append(f"[Tool: {part.get('tool', '?')}]")
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
    Versão otimizada: prompt simplificado, timeout 2.5min, parsing robusto.
    """
    print("[AUDITOR] Iniciando auditoria do repositório...")
    
    client = None
    try:
        # Coletar contexto do repo (rápido)
        repo_context = await _get_repo_context()
        print(f"[AUDITOR] Contexto coletado: {len(repo_context)} chars")
        
        # Criar cliente OpenCode
        config = OpenCodeConfig(
            server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
            password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
        )
        client = OpenCodeClient(config)
        await client.connect()
        
        try:
            # Executar auditor com timeout total
            resposta = await asyncio.wait_for(
                _run_auditor_prompt(client, AUDITOR_PROMPT + f"\n\nContexto do repositório:\n{repo_context}"),
                timeout=150.0  # 2.5 min total
            )
            print(f"[AUDITOR] Resposta bruta: {len(resposta)} chars")
            
            # Parsear resposta
            plano_json = _parse_auditor_response(resposta)
            total_acoes = sum(len(e.get('acoes_propostas', [])) for e in plano_json.get('etapas', []))
            print(f"[AUDITOR] Plano parseado: {len(plano_json.get('etapas', []))} etapas, {total_acoes} ações")
            
            if total_acoes == 0:
                print("[AUDITOR] WARNING: Nenhuma ação gerada pelo auditor")
            
            # Converter para estado
            novo_state = _converter_plano_para_estado(plano_json, state)
            
            total_acoes_final = len(novo_state.get("acoes_pendentes", []))
            print(f"[AUDITOR] Plano final: {len(novo_state.get('fundamentos', []))} fundamentos, "
                  f"{len(novo_state.get('etapas', []))} etapas, {total_acoes_final} ações")
            
            return {
                "fundamentos": novo_state["fundamentos"],
                "etapas": novo_state["etapas"],
                "acoes_pendentes": novo_state["acoes_pendentes"],
                "metadata": {
                    **state.get("metadata", {}),
                    "auditoria_gerada_em": datetime.now().isoformat(),
                    "total_acoes_geradas": total_acoes_final,
                }
            }
            
        except asyncio.TimeoutError:
            print("[AUDITOR] TIMEOUT: Auditor excedeu 2.5 min")
            return {
                "metadata": {
                    **state.get("metadata", {}),
                    "auditoria_erro": "Timeout: auditor excedeu 2.5 min",
                    "auditoria_gerada_em": datetime.now().isoformat(),
                }
            }
        except Exception as e:
            print(f"[AUDITOR] Erro: {e}")
            return {
                "metadata": {
                    **state.get("metadata", {}),
                    "auditoria_erro": str(e),
                    "auditoria_gerada_em": datetime.now().isoformat(),
                }
            }
        finally:
            if client:
                await client.close()
            
    except Exception as e:
        print(f"[AUDITOR] Erro crítico: {e}")
        return {
            "metadata": {
                **state.get("metadata", {}),
                "auditoria_erro": f"Erro crítico: {e}",
                "auditoria_gerada_em": datetime.now().isoformat(),
            }
        }


# Função wrapper para compatibilidade com o grafo
async def auditor_node(state: HarmoniaState) -> dict:
    """Wrapper assíncrono para o nó auditor."""
    return await auditor(state)