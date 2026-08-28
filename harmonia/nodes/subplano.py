from __future__ import annotations

from harmonia.graph.state import (
    HarmoniaState, 
    NivelRisco,
    make_subplano,
    make_acao_proposta,
)


def _diagnosticar_divergencia(acao: dict, state: HarmoniaState) -> dict:
    fundamentos_atuais = {f["id"]: f["descricao"] for f in state.get("fundamentos", [])}
    
    fundamentos_acao = acao.get("parametros", {}).get("fundamentos_ids", [])
    divergentes = [fid for fid in fundamentos_acao if fid not in fundamentos_atuais]
    
    return {
        "fundamento_divergente_id": divergentes[0] if divergentes else None,
        "fundamento_alterado": acao.get("parametros", {}).get("fundamento_alterado", False),
        "descricao": acao.get("parametros", {}).get("descricao_divergencia", "Fundamento nao encontrado no plano atual"),
    }


def _criar_subplano(acao: dict, diagnostico: dict, state: HarmoniaState) -> dict:
    profundidade = len(state.get("subplanos_ativos", [])) + 1
    
    acoes_resolucao = _gerar_acoes_resolucao(acao, diagnostico, state)
    
    subplano = make_subplano(
        acao_origem_id=acao.get("id", ""),
        fundamento_divergente_id=diagnostico.get("fundamento_divergente_id") or "",
        descricao=f"Subplano para resolver divergencia: {diagnostico.get('descricao', '')}",
        profundidade=profundidade,
        acoes=acoes_resolucao,
    )
    
    return subplano


def _gerar_acoes_resolucao(
    acao_origem: dict, 
    diagnostico: dict, 
    state: HarmoniaState,
) -> list[dict]:
    acoes = []
    
    acao_investigar = make_acao_proposta(
        tipo="investigar_divergencia",
        descricao=f"Investigar mudanca no fundamento {diagnostico.get('fundamento_divergente_id', '')}",
        parametros={
            "fundamento_id": diagnostico.get("fundamento_divergente_id"),
            "acao_origem_id": acao_origem.get("id", ""),
        },
        risco=NivelRisco.BAIXO.value,
        raciocinio="Entender o que mudou no fundamento antes de replanejar",
        reversivel=True,
        max_tentativas=1,
    )
    acoes.append(acao_investigar)
    
    acao_replanejar = make_acao_proposta(
        tipo="replanejar_etapa",
        descricao="Replanejar etapa afetada pela mudanca de fundamento",
        parametros={
            "acao_origem_id": acao_origem.get("id", ""),
            "fundamento_id": diagnostico.get("fundamento_divergente_id"),
        },
        risco=NivelRisco.MEDIO.value,
        raciocinio="Ajustar o plano para o novo fundamento",
        reversivel=True,
        max_tentativas=1,
    )
    acoes.append(acao_replanejar)
    
    return acoes


def processar_subplano(state: HarmoniaState) -> dict:
    acoes_pendentes = list(state.get("acoes_pendentes", []))
    subplanos_ativos = list(state.get("subplanos_ativos", []))
    
    if not acoes_pendentes:
        return {}
    
    acao = dict(acoes_pendentes[0])
    
    if acao.get("risco") != NivelRisco.MEDIO.value:
        return {}
    
    subplanos_existentes = [s for s in subplanos_ativos if s.get("acao_origem_id") == acao.get("id")]
    
    if subplanos_existentes:
        subplano = dict(subplanos_existentes[0])
        
        if subplano.get("status") == "resolvido":
            subplano_acoes = subplano.get("acoes", [])
            new_subplanos = [s for s in subplanos_ativos if s.get("id") != subplano["id"]]
            return {
                "acoes_pendentes": subplano_acoes + acoes_pendentes[1:],
                "subplanos_ativos": new_subplanos,
            }
        
        max_prof = state.get("max_profundidade_subplano", 1)
        if subplano.get("profundidade", 0) > max_prof:
            subplano["status"] = "escalado"
            new_subplanos = [subplano if s.get("id") == subplano["id"] else s for s in subplanos_ativos]
            return {
                "subplanos_ativos": new_subplanos,
                "mensagem_final": f"Subplano {subplano.get('id')} excedeu profundidade maxima. Escalando para decisao humana.",
                "criterio_parada_seguranca": True,
            }
        
        subplano_acoes = list(subplano.get("acoes", []))
        if subplano_acoes:
            proxima = subplano_acoes[0]
            subplano["acoes"] = subplano_acoes[1:]
            new_subplanos = [subplano if s.get("id") == subplano["id"] else s for s in subplanos_ativos]
            return {
                "acoes_pendentes": [proxima] + acoes_pendentes[1:],
                "subplanos_ativos": new_subplanos,
            }
        
        from datetime import datetime
        subplano["status"] = "resolvido"
        subplano["resolvido_em"] = datetime.now().isoformat()
        new_subplanos = [subplano if s.get("id") == subplano["id"] else s for s in subplanos_ativos]
        return {
            "subplanos_ativos": new_subplanos,
        }
    
    diagnostico = _diagnosticar_divergencia(acao, state)
    subplano = _criar_subplano(acao, diagnostico, state)
    
    new_subplanos = subplanos_ativos + [subplano]
    subplano_acoes = subplano.get("acoes", [])
    
    return {
        "subplanos_ativos": new_subplanos,
        "acoes_pendentes": subplano_acoes + acoes_pendentes[1:],
    }
