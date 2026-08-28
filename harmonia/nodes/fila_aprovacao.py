from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import unicodedata

from langgraph.types import interrupt
from langgraph.graph import END

from harmonia.graph.state import (
    HarmoniaState, 
    NivelRisco,
    make_solicitacao_aprovacao,
)


def _normalizar(texto: str) -> str:
    """Remove acentos, converte para minusculas e remove pontuacao para comparacao."""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


INTERVALOS_TENTATIVA = {
    NivelRisco.ALTO.value: timedelta(minutes=5),
    NivelRisco.MEDIO.value: timedelta(minutes=15),
    NivelRisco.BAIXO.value: timedelta(minutes=30),
}


def _construir_mensagem_aprovacao(acao: dict, state: HarmoniaState) -> str:
    linhas = [
        f"[APROVACAO NECESSARIA] (Risco: {acao.get('risco', 'baixo').upper()})",
        f"",
        f"Acao: {acao.get('descricao', '')}",
        f"Tipo: {acao.get('tipo', '')}",
        f"Raciocinio: {acao.get('raciocinio', '')}",
        f"Impacto estimado: {acao.get('impacto_estimado') or 'Nao especificado'}",
        f"",
    ]
    
    if acao.get("rollback"):
        linhas.append(f"Rollback: {acao['rollback']}")
    
    if acao.get("reversivel", True):
        linhas.append("Reversivel: [SIM]")
    else:
        linhas.append("Reversivel: [NAO] -- acao irreversivel")
    
    if acao.get("risco") == NivelRisco.ALTO.value:
        linhas.extend([
            "",
            "[ATENCAO] CONFIRMACAO QUALIFICADA OBRIGATORIA",
            "Responda repetindo o resumo da acao para confirmar que leu e entendeu.",
        ])
    
    return "\n".join(linhas)


def _calcular_prazo_validade(risco: str) -> str:
    base = datetime.now()
    if risco == NivelRisco.ALTO.value:
        prazo = base + timedelta(hours=1)
    elif risco == NivelRisco.MEDIO.value:
        prazo = base + timedelta(hours=4)
    else:
        prazo = base + timedelta(hours=24)
    return prazo.isoformat()


def _enviar_para_telegram(solicitacao: dict, state: HarmoniaState):
    """Envia solicitacao de aprovacao via Telegram API (sincrono)."""
    import os
    import json
    import urllib.request
    from pathlib import Path

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        print(f"[TELEGRAM] Bot token nao configurado. Skip.")
        return

    allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    if allowed:
        chat_id = int(allowed.split(",")[0].strip())
    else:
        # project root = 3 níveis acima de harmonia/nodes/
        chat_id_file = Path(__file__).parent.parent.parent / ".telegram_chat_id"
        if chat_id_file.exists():
            chat_id = int(chat_id_file.read_text().strip())
        else:
            print(f"[TELEGRAM] Nenhum chat_id configurado. Mande /start para o bot.")
            return
    thread_id = state.get("plano_id", "")
    sol_id = solicitacao.get("id", "")
    msg = solicitacao.get("mensagem", "")

    botoes = {
        "inline_keyboard": [[
            {"text": "✅ Aprovar", "callback_data": f"aprovar:{sol_id}:{thread_id}"},
            {"text": "❌ Rejeitar", "callback_data": f"rejeitar:{sol_id}:{thread_id}"},
        ]]
    }

    payload = json.dumps({
        "chat_id": chat_id,
        "text": msg,
        "reply_markup": botoes,
    }).encode("utf-8")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("ok"):
                print(f"[TELEGRAM] Mensagem enviada para {chat_id}: sol_id={sol_id}")
            else:
                print(f"[TELEGRAM] Erro API: {data}")
    except Exception as e:
        print(f"[TELEGRAM] Erro ao enviar: {e}")


def preparar_aprovacao(state: HarmoniaState) -> dict:
    """Prepara a solicitacao de aprovacao e adiciona a fila."""
    acoes_pendentes = state.get("acoes_pendentes", [])
    
    if not acoes_pendentes:
        return {}
    
    acao = dict(acoes_pendentes[0])
    fila = list(state.get("fila_aprovacao", []))
    
    if acao.get("status") == "aguardando_aprovacao":
        # Ja existe solicitacao - nao criar duplicata
        return {}
    
    risco = acao.get("risco", "baixo")
    is_alto = risco == NivelRisco.ALTO.value
    
    solicitacao = make_solicitacao_aprovacao(
        acao_id=acao.get("id", ""),
        mensagem=_construir_mensagem_aprovacao(acao, state),
        max_tentativas=3,
        prazo_validade=_calcular_prazo_validade(risco),
        confirmacao_qualificada=is_alto,
    )
    
    new_fila = fila + [solicitacao]
    acao["status"] = "aguardando_aprovacao"
    
    _enviar_para_telegram(solicitacao, state)
    
    return {
        "acoes_pendentes": [acao] + acoes_pendentes[1:],
        "fila_aprovacao": new_fila,
    }


def aguardar_aprovacao(state: HarmoniaState) -> dict:
    """Aguarda aprovacao via interrupt()."""
    acoes_pendentes = state.get("acoes_pendentes", [])
    
    if not acoes_pendentes:
        return {}
    
    acao = dict(acoes_pendentes[0])
    fila = list(state.get("fila_aprovacao", []))
    
    solicitacoes_existentes = [
        s for s in fila 
        if s.get("acao_id") == acao.get("id") and s.get("status") == "pendente"
    ]
    
    if not solicitacoes_existentes:
        return {}
    
    solicitacao = dict(solicitacoes_existentes[0])
    
    prazo = solicitacao.get("prazo_validade")
    if prazo and datetime.now() > datetime.fromisoformat(prazo):
        solicitacao["status"] = "expirada"
        acao["status"] = "expirada"
        acao["erro"] = "Solicitacao de aprovacao expirada apos 3 tentativas"
        
        new_fila = [solicitacao if s.get("id") == solicitacao["id"] else s for s in fila]
        
        return {
            "acoes_pendentes": [acao] + acoes_pendentes[1:],
            "fila_aprovacao": new_fila,
            "mensagem_final": f"Acao {acao.get('id')} expirada sem resposta. Nao executada.",
            "criterio_parada_seguranca": True,
        }
    
    resposta = interrupt({
        "tipo": "aprovacao_pendente" if solicitacao.get("tentativas_contato", 0) > 0 else "nova_aprovacao",
        "solicitacao_id": solicitacao.get("id"),
        "acao_id": acao.get("id"),
        "mensagem": solicitacao.get("mensagem", ""),
        "tentativa": solicitacao.get("tentativas_contato", 0) + 1,
        "max_tentativas": solicitacao.get("max_tentativas", 3),
        "confirmacao_qualificada": solicitacao.get("confirmacao_qualificada", False),
    })
    
    if resposta:
        solicitacao["resposta"] = resposta.get("resposta", "") if isinstance(resposta, dict) else str(resposta)
        solicitacao["respondido_em"] = datetime.now().isoformat()
        
        aprovado = not isinstance(resposta, dict) or resposta.get("aprovado", True)
        
        if not aprovado:
            solicitacao["status"] = "rejeitada"
            acao["status"] = "rejeitada"
            acao["erro"] = "Rejeitada pelo usuario"
            new_fila = [s for s in fila if s.get("id") != solicitacao["id"]]
            return {
                "acoes_pendentes": [acao] + acoes_pendentes[1:],
                "fila_aprovacao": new_fila,
                "mensagem_final": f"Acao {acao.get('id')} rejeitada pelo usuario.",
            }
        
        solicitacao["status"] = "respondida"
        
        if solicitacao.get("confirmacao_qualificada"):
            resumo_esperado = _normalizar(acao.get("descricao", "")[:100])
            resposta_usuario = _normalizar(solicitacao["resposta"])
            
            if not resumo_esperado or resumo_esperado not in resposta_usuario:
                solicitacao["status"] = "rejeitada"
                acao["status"] = "rejeitada"
                acao["erro"] = "Confirmacao qualificada falhou: resumo nao conferido"
                new_fila = [s for s in fila if s.get("id") != solicitacao["id"]]
                return {
                    "acoes_pendentes": [acao] + acoes_pendentes[1:],
                    "fila_aprovacao": new_fila,
                    "mensagem_final": f"Acao {acao.get('id')} rejeitada: confirmacao qualificada invalida.",
                }
        
        acao["status"] = "pendente"
        new_fila = [s for s in fila if s.get("id") != solicitacao["id"]]
        return {
            "acoes_pendentes": [acao] + acoes_pendentes[1:],
            "fila_aprovacao": new_fila,
        }
    
    solicitacao["tentativas_contato"] = solicitacao.get("tentativas_contato", 0) + 1
    
    if solicitacao["tentativas_contato"] >= solicitacao.get("max_tentativas", 3):
        solicitacao["status"] = "expirada"
        acao["status"] = "expirada"
        acao["erro"] = "Maximo de tentativas de contato atingido sem resposta"
        
        new_fila = [solicitacao if s.get("id") == solicitacao["id"] else s for s in fila]
        return {
            "acoes_pendentes": [acao] + acoes_pendentes[1:],
            "fila_aprovacao": new_fila,
            "mensagem_final": f"Acao {acao.get('id')} expirada apos {solicitacao.get('max_tentativas', 3)} tentativas. Nao executada.",
            "criterio_parada_seguranca": True,
        }
    
    new_fila = [solicitacao if s.get("id") == solicitacao["id"] else s for s in fila]
    return {
        "acoes_pendentes": [acao] + acoes_pendentes[1:],
        "fila_aprovacao": new_fila,
    }


# Alias para compatibilidade
def fila_aprovacao(state: HarmoniaState) -> dict:
    """Funcao original mantida para compatibilidade - delega para preparar_aprovacao."""
    return preparar_aprovacao(state)