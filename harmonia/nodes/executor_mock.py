from __future__ import annotations

from datetime import datetime
from harmonia.graph.state import HarmoniaState, make_log_rastro


async def executar_acao_mock(state: HarmoniaState) -> dict:
    """Mock executor: cria arquivo real no disco, simula sucesso OpenCode."""
    if not state.get("acoes_pendentes"):
        return {}
    
    acoes_pendentes = state.get("acoes_pendentes", [])
    acao = dict(acoes_pendentes[0])
    remaining = acoes_pendentes[1:]
    acoes_executadas = list(state.get("acoes_executadas", []))
    log_rastro = list(state.get("log_rastro", []))
    
    acao["status"] = "executando"
    acao["executado_em"] = datetime.now().isoformat()
    
    estado_antes = {
        "acoes_pendentes_count": len(remaining),
        "acoes_executadas_count": len(acoes_executadas),
    }
    
    # SIMULAÇÃO REAL: cria arquivo no disco
    if acao.get("tipo") == "editar_arquivo":
        arquivo = acao.get("parametros", {}).get("arquivo", "/tmp/teste_harmonia.txt")
        conteudo = acao.get("parametros", {}).get("conteudo", "harmonia funcionou")
        try:
            with open(arquivo, "w") as f:
                f.write(conteudo)
            acao["status"] = "concluida"
            acao["resultado"] = {
                "output": f"Arquivo {arquivo} criado com sucesso",
                "arquivo": arquivo,
                "conteudo": conteudo
            }
        except Exception as e:
            acao["status"] = "falhou"
            acao["erro"] = str(e)
    else:
        acao["status"] = "concluida"
        acao["resultado"] = {"output": f"Mock executado: {acao.get('descricao')}"}
    
    estado_depois = {
        "acoes_pendentes_count": len(remaining),
        "acoes_executadas_count": len(state.get("acoes_executadas", [])) + 1,
        "ultimo_resultado": acao.get("resultado"),
    }
    
    log = make_log_rastro(
        acao_id=acao.get("id", ""),
        estado_antes={
            "acoes_pendentes_count": len(remaining),
            "acoes_executadas_count": len(state.get("acoes_executadas", [])),
        },
        estado_depois={
            "acoes_pendentes_count": len(remaining),
            "acoes_executadas_count": len(state.get("acoes_executadas", [])) + 1,
            "ultimo_resultado": acao.get("resultado"),
        },
        reversivel=acao.get("reversivel", True),
        causa=f"Mock execução: {acao.get('descricao', '')}",
    )
    
    return {
        "acoes_pendentes": list(state.get("acoes_pendentes", []))[1:],
        "acoes_executadas": list(state.get("acoes_executadas", [])) + [acao],
        "log_rastro": list(state.get("log_rastro", [])) + [log],
    }