from __future__ import annotations

from harmonia.graph.state import HarmoniaState, AcaoProposta, NivelRisco


def _e_irreversivel(acao: AcaoProposta) -> bool:
    tipo = acao.get("tipo", "").lower()
    params = acao.get("parametros", {})
    
    irreversiveis = {
        "deploy_producao",
        "push_protected_branch",
        "delete_recurso",
        "gasto_creditos",
        "escrita_sistema_externo",
        "migracao_banco_irreversivel",
    }
    
    if tipo in irreversiveis:
        return True
    
    if tipo == "comando" and params.get("destrutivo", False):
        return True
    
    if tipo == "api_call" and not params.get("reversivel", True):
        return True
    
    return False


def _envolve_recurso_externo(acao: AcaoProposta) -> bool:
    tipo = acao.get("tipo", "").lower()
    params = acao.get("parametros", {})
    
    if tipo in {"gasto_creditos", "api_call_paga", "criar_recurso_cloud", "transacao_financeira"}:
        return True
    
    if tipo == "api_call" and params.get("paga", False):
        return True
    
    if tipo == "comando" and any(k in str(params).lower() for k in ["aws", "gcp", "azure", "stripe", "openai", "anthropic"]):
        return True
    
    return False


def _afeta_terceiro(acao: AcaoProposta) -> bool:
    tipo = acao.get("tipo", "").lower()
    params = acao.get("parametros", {})
    
    if tipo in {"abrir_pr", "notificar_stakeholder", "deploy_compartilhado", "webhook_terceiro", "escrita_compartilhada"}:
        return True
    
    if tipo == "git" and params.get("abrir_pr", False):
        return True
    
    if tipo == "deploy" and params.get("ambiente") in {"staging", "homologacao", "producao"}:
        return True
    
    return False


def _e_recorrente_operacional(acao: AcaoProposta) -> bool:
    tipo = acao.get("tipo", "").lower()
    
    operacionais = {
        "editar_arquivo",
        "ler_arquivo",
        "buscar_codigo",
        "rodar_lint",
        "rodar_testes",
        "build_local",
        "retry_api",
        "trocar_modelo",
        "comando_readonly",
        "consulta_banco",
        "ver_log",
    }
    
    if tipo in operacionais:
        return True
    
    if tipo == "comando" and acao.get("parametros", {}).get("readonly", False):
        return True
    
    return False


def _diverge_fundamento(acao: AcaoProposta, state: HarmoniaState) -> bool:
    fundamentos_atuais = {f["id"]: f["descricao"] for f in state.get("fundamentos", [])}
    
    for fund_id in acao.get("parametros", {}).get("fundamentos_ids", []):
        if fund_id not in fundamentos_atuais:
            return True
    
    if acao.get("parametros", {}).get("fundamento_alterado", False):
        return True
    
    return False


def classificar_risco(state: HarmoniaState) -> dict:
    acoes_pendentes = state.get("acoes_pendentes", [])
    
    if not acoes_pendentes:
        return {}
    
    acao = dict(acoes_pendentes[0])
    
    if _e_irreversivel(acao):
        acao["risco"] = NivelRisco.ALTO.value
    elif _envolve_recurso_externo(acao):
        acao["risco"] = NivelRisco.ALTO.value
    elif _afeta_terceiro(acao):
        acao["risco"] = NivelRisco.ALTO.value
    elif _diverge_fundamento(acao, state):
        acao["risco"] = NivelRisco.MEDIO.value
    elif _e_recorrente_operacional(acao):
        acao["risco"] = NivelRisco.BAIXO.value
    else:
        acao["risco"] = NivelRisco.MEDIO.value
    
    return {"acoes_pendentes": [acao] + acoes_pendentes[1:]}
