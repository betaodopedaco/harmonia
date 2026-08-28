from __future__ import annotations

from harmonia.graph.state import (
    HarmoniaState, 
    make_sinal_autoavaliacao,
)


def _comparar_com_fundamentos(acao: dict, state: HarmoniaState) -> dict:
    fundamentos_relevantes = [
        f for f in state.get("fundamentos", [])
        if f.get("id") in acao.get("parametros", {}).get("fundamentos_ids", [])
    ]
    
    if not fundamentos_relevantes:
        return {
            "divergencia": False,
            "confianca": 1.0,
            "descricao": "Nenhum fundamento associado a acao",
        }
    
    resultado = acao.get("resultado") or {}
    sucesso = acao.get("status") == "concluida"
    
    divergencia = False
    confianca = 1.0
    descricoes = []
    
    for fund in fundamentos_relevantes:
        fund_desc = fund.get("descricao", "").lower()
        
        if "qualidade" in fund_desc and not sucesso:
            divergencia = True
            confianca = min(confianca, 0.3)
            descricoes.append(f"Fundamento '{fund.get('descricao')}' violado: acao falhou")
        
        if "tempo" in fund_desc or "prazo" in fund_desc:
            tempo_exec = resultado.get("tempo_execucao_segundos", 0)
            if tempo_exec > 300:
                divergencia = True
                confianca = min(confianca, 0.5)
                descricoes.append(f"Fundamento '{fund.get('descricao')}' em risco: execucao demorou {tempo_exec}s")
        
        if "custo" in fund_desc or "orcamento" in fund_desc:
            custo = resultado.get("custo_estimado", 0)
            if custo > 100:
                divergencia = True
                confianca = min(confianca, 0.4)
                descricoes.append(f"Fundamento '{fund.get('descricao')}' em risco: custo {custo}")
    
    return {
        "divergencia": divergencia,
        "confianca": confianca,
        "descricao": "; ".join(descricoes) if descricoes else "Alinhado com fundamentos",
    }


def _verificar_duas_divergencias_seguidas(state: HarmoniaState) -> bool:
    sinais = state.get("sinais_autoavaliacao", [])
    if len(sinais) < 2:
        return False
    
    ultimos = sinais[-2:]
    return all(s.get("divergencia_detectada") and s.get("requer_pausa") for s in ultimos)


def autoavaliar(state: HarmoniaState) -> dict:
    acoes_executadas = state.get("acoes_executadas", [])
    sinais = list(state.get("sinais_autoavaliacao", []))
    
    if not acoes_executadas:
        return {}
    
    ultima_acao = acoes_executadas[-1]
    
    ja_avaliou = any(
        s.get("acao_id") == ultima_acao.get("id") 
        for s in sinais
    )
    
    if ja_avaliou:
        return {}
    
    comparacao = _comparar_com_fundamentos(ultima_acao, state)
    
    sinal = make_sinal_autoavaliacao(
        acao_id=ultima_acao.get("id", ""),
        divergencia_detectada=comparacao["divergencia"],
        descricao=comparacao["descricao"],
        confianca=comparacao["confianca"],
        requer_pausa=comparacao["divergencia"] and comparacao["confianca"] < 0.7,
    )
    
    new_sinais = sinais + [sinal]
    
    result = {"sinais_autoavaliacao": new_sinais}
    
    if _verificar_duas_divergencias_seguidas({"sinais_autoavaliacao": new_sinais}):
        result["criterio_parada_seguranca"] = True
        result["mensagem_final"] = "Autoavaliacao detectou divergencia da intencao 2x seguida. Parada de seguranca automatica."
    
    return result
