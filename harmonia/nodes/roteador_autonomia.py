from __future__ import annotations

from harmonia.graph.state import HarmoniaState, DialAutonomia, NivelRisco


LIMIARES = {
    DialAutonomia.LIGADAO.value: {
        NivelRisco.BAIXO.value: "executar",
        NivelRisco.MEDIO.value: "aprovar",
        NivelRisco.ALTO.value: "aprovar",
    },
    DialAutonomia.SONINHO.value: {
        NivelRisco.BAIXO.value: "executar",
        NivelRisco.MEDIO.value: "executar",
        NivelRisco.ALTO.value: "aprovar",
    },
}


HISTORICO_ACERTOS: dict[str, dict[str, int]] = {}


def _registrar_acerto(categoria: str, acertou: bool):
    if categoria not in HISTORICO_ACERTOS:
        HISTORICO_ACERTOS[categoria] = {"total": 0, "acertos": 0}
    
    HISTORICO_ACERTOS[categoria]["total"] += 1
    if acertou:
        HISTORICO_ACERTOS[categoria]["acertos"] += 1


def _taxa_acerto(categoria: str) -> float:
    if categoria not in HISTORICO_ACERTOS:
        return 0.0
    
    h = HISTORICO_ACERTOS[categoria]
    if h["total"] == 0:
        return 0.0
    
    return h["acertos"] / h["total"]


def _categoria_migrou_para_autonomia(categoria: str, dial: str) -> bool:
    if dial != DialAutonomia.LIGADAO.value:
        return False
    
    taxa = _taxa_acerto(categoria)
    return taxa >= 0.95 and HISTORICO_ACERTOS.get(categoria, {}).get("total", 0) >= 10


def reset_historico_acertos():
    global HISTORICO_ACERTOS
    HISTORICO_ACERTOS = {}


def rotear_autonomia(state: HarmoniaState) -> dict:
    acoes_pendentes = state.get("acoes_pendentes", [])
    
    if not acoes_pendentes:
        return {}
    
    acao = dict(acoes_pendentes[0])
    dial = state.get("dial_autonomia", DialAutonomia.SONINHO.value)
    risco = acao.get("risco", "baixo")
    
    categoria_chave = f"{risco}_{acao.get('tipo', '')}"
    
    metadata = dict(acao.get("metadata", {}))
    
    if _categoria_migrou_para_autonomia(categoria_chave, dial):
        metadata["autonomia_concedida"] = True
        metadata["motivo"] = f"Taxa de acerto {_taxa_acerto(categoria_chave):.1%} >= 95%"
        acao["metadata"] = metadata
        return {"acoes_pendentes": [acao] + acoes_pendentes[1:]}
    
    limiares_dial = LIMIARES.get(dial, LIMIARES[DialAutonomia.SONINHO.value])
    decisao = limiares_dial.get(risco, "aprovar")
    
    metadata["roteador_decisao"] = decisao
    metadata["dial"] = dial
    metadata["risco"] = risco
    acao["metadata"] = metadata
    
    return {"acoes_pendentes": [acao] + acoes_pendentes[1:]}
