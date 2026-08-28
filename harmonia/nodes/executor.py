from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime
from typing import Any

from harmonia.graph.state import HarmoniaState, AcaoProposta, make_log_rastro


_opencode_client = None
_opencode_lock = asyncio.Lock()

# Configuração de git para commits automáticos
_GIT_CONFIGURED = False


async def _configurar_git():
    """Configura git user.name e user.email se não estiverem setados."""
    global _GIT_CONFIGURED
    if _GIT_CONFIGURED:
        return
    
    try:
        # Verificar se já tem config
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, cwd="/workspaces/harmonia"
        )
        if not result.stdout.strip():
            subprocess.run(
                ["git", "config", "user.name", "Harmonia Bot"],
                check=True, cwd="/workspaces/harmonia"
            )
        
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, cwd="/workspaces/harmonia"
        )
        if not result.stdout.strip():
            subprocess.run(
                ["git", "config", "user.email", "harmonia@bot.local"],
                check=True, cwd="/workspaces/harmonia"
            )
        
        _GIT_CONFIGURED = True
        print("[GIT] Configuração verificada/aplicada")
    except Exception as e:
        print(f"[GIT] Erro ao configurar: {e}")


async def _auto_commit(acao: dict, aprovado_via_telegram: bool = False):
    """Faz commit automático das mudanças após execução bem-sucedida."""
    try:
        await _configurar_git()
        
        # Verificar se há mudanças para commitar
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd="/workspaces/harmonia"
        )
        if not result.stdout.strip():
            print("[GIT] Nenhuma mudança para commitar")
            return
        
        # Stage todas as mudanças
        subprocess.run(
            ["git", "add", "-A"],
            check=True, cwd="/workspaces/harmonia"
        )
        
        # Montar mensagem de commit
        descricao = acao.get("descricao", "")[:80]
        risco = acao.get("risco", "baixo").upper()
        aprovacao = "aprovado_via_Telegram" if aprovado_via_telegram else "aprovado_automaticamente"
        
        mensagem = f"Harmonia: {descricao} — {risco} risco, {aprovacao}"
        
        # Commit
        subprocess.run(
            ["git", "commit", "-m", mensagem],
            check=True, cwd="/workspaces/harmonia"
        )
        
        print(f"[GIT] Commit realizado: {mensagem}")
        
    except Exception as e:
        print(f"[GIT] Erro no auto-commit: {e}")


async def _get_opencode_client():
    global _opencode_client
    async with _opencode_lock:
        if _opencode_client is None:
            from harmonia.integrations.opencode_client import OpenCodeClient
            server_url = os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096")
            password = os.getenv("OPENCODE_SERVER_PASSWORD", "")
            _opencode_client = OpenCodeClient()
            _opencode_client.config.server_url = server_url
            _opencode_client.config.password = password
            await _opencode_client.connect()
        return _opencode_client


def _construir_prompt_acao(acao: AcaoProposta) -> str:
    partes = [
        f"Tarefa: {acao.get('descricao', '')}",
        f"Tipo: {acao.get('tipo', '')}",
        "",
    ]
    
    params = acao.get("parametros", {})
    if params:
        partes.append("Parametros:")
        for k, v in params.items():
            partes.append(f"  - {k}: {v}")
        partes.append("")
    
    if acao.get("raciocinio"):
        partes.append(f"Contexto/Raciocinio: {acao['raciocinio']}")
        partes.append("")
    
    if acao.get("rollback"):
        partes.append(f"Rollback (se falhar): {acao['rollback']}")
    
    return "\n".join(partes)


async def _executar_com_auto_aprovacao(client, acao: AcaoProposta, session_title: str) -> "ExecutionResult":
    """
    Executa ação no OpenCode com auto-aprovação de permissões para baixo risco.
    
    Usa execute() síncrono que aguarda conclusão completa do OpenCode.
    Se surgir permissão pendente durante execução, auto-aprova para baixo risco.
    """
    from harmonia.integrations.opencode_client import ExecutionResult
    
    risco = acao.get("risco", "baixo")
    
    # Executar de forma síncrona (bloqueia até OpenCode terminar)
    resultado = await client.execute(
        prompt=_construir_prompt_acao(acao),
        session_title=session_title,
        model="nvidia/nemotron-3-ultra",
    )
    
    print(f"[Executor] Resultado OpenCode: success={resultado.success}, output_len={len(resultado.output)}, error={resultado.error}")
    
    return resultado


async def executar_acao(state: HarmoniaState) -> dict:
    acoes_pendentes = state.get("acoes_pendentes", [])
    acoes_executadas = list(state.get("acoes_executadas", []))
    log_rastro = list(state.get("log_rastro", []))
    
    if not acoes_pendentes:
        return {}
    
    acao = dict(acoes_pendentes[0])
    remaining = acoes_pendentes[1:]
    
    acao["status"] = "executando"
    acao["executado_em"] = datetime.now().isoformat()
    
    estado_antes = {
        "acoes_pendentes_count": len(remaining),
        "acoes_executadas_count": len(acoes_executadas),
    }
    
    try:
        client = await _get_opencode_client()
        
        session_title = f"harmonia-{acao.get('tipo', '')}-{acao.get('id', '')[:8]}"
        resultado = await _executar_com_auto_aprovacao(client, acao, session_title)
        
        if resultado.success:
            acao["status"] = "concluida"
            acao["resultado"] = {
                "output": resultado.output,
                "messages": resultado.messages,
                "session_id": resultado.session_id,
            }
            
            # Auto-commit das mudanças
            aprovado_via_telegram = acao.get("status") == "concluida" and acao.get("risco") == "alto"
            await _auto_commit(acao, aprovado_via_telegram)
            
            estado_depois = {
                "acoes_pendentes_count": len(remaining),
                "acoes_executadas_count": len(acoes_executadas) + 1,
                "ultimo_resultado": acao.get("resultado"),
            }
        else:
            acao["status"] = "falhou"
            acao["erro"] = resultado.error or "Falha desconhecida na execucao"
            acao["tentativas"] = acao.get("tentativas", 0) + 1
            
            estado_depois = {
                "acoes_pendentes_count": len(remaining),
                "acoes_executadas_count": len(acoes_executadas),
                "erro": acao.get("erro"),
            }
            
            if acao.get("tentativas", 0) < acao.get("max_tentativas", 3) and acao.get("risco") == "baixo":
                return {"acoes_pendentes": [acao] + remaining}
    
    except Exception as e:
        acao["status"] = "falhou"
        acao["erro"] = str(e)
        acao["tentativas"] = acao.get("tentativas", 0) + 1
        
        estado_depois = {
            "acoes_pendentes_count": len(remaining),
            "acoes_executadas_count": len(acoes_executadas),
            "erro": str(e),
        }
        
        if acao.get("tentativas", 0) < acao.get("max_tentativas", 3) and acao.get("risco") == "baixo":
            return {"acoes_pendentes": [acao] + remaining}
    
    log = make_log_rastro(
        acao_id=acao.get("id", ""),
        estado_antes=estado_antes,
        estado_depois=estado_depois,
        reversivel=acao.get("reversivel", True),
        causa=f"Execucao via OpenCode: {acao.get('descricao', '')}",
    )
    
    return {
        "acoes_pendentes": remaining,
        "acoes_executadas": acoes_executadas + [acao],
        "log_rastro": log_rastro + [log],
    }


async def fechar_cliente_opencode() -> None:
    global _opencode_client
    async with _opencode_lock:
        if _opencode_client:
            await _opencode_client.close()
            _opencode_client = None
