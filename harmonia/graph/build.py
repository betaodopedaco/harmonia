from __future__ import annotations

import os
import asyncio
import aiosqlite
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from harmonia.graph.state import HarmoniaState, DialAutonomia, make_fundamento, make_etapa_plano, make_acao_proposta
from harmonia.nodes.auditor import auditor_node
from harmonia.nodes.classificador_risco import classificar_risco
from harmonia.nodes.roteador_autonomia import rotear_autonomia
from harmonia.nodes.fila_aprovacao import preparar_aprovacao, aguardar_aprovacao
from harmonia.nodes.executor import executar_acao
from harmonia.nodes.subplano import processar_subplano
from harmonia.nodes.autoavaliacao import autoavaliar


CHECKPOINT_DB = os.getenv("HARMONIA_CHECKPOINT_DB", "harmonia_checkpoints.db")


def _deve_ir_para_aprovacao(state: HarmoniaState) -> Literal["aprovar", "executar", "subplano", "fim"]:
    acoes_pendentes = state.get("acoes_pendentes", [])
    
    if not acoes_pendentes:
        return "fim"
    
    acao = acoes_pendentes[0]
    risco = acao.get("risco", "baixo")
    
    if risco == "alto":
        return "aprovar"
    elif risco == "medio":
        return "subplano"
    else:
        return "executar"


def _deve_continuar_apos_aprovacao(state: HarmoniaState) -> Literal["continuar", "fim"]:
    """Verifica se a aprovacao foi concedida (acao voltou para pendente)."""
    acoes_pendentes = state.get("acoes_pendentes", [])
    
    if not acoes_pendentes:
        return "fim"
    
    acao = acoes_pendentes[0]
    status = acao.get("status", "pendente")
    
    if status == "pendente":
        return "continuar"
    elif status in ("rejeitada", "expirada"):
        return "fim"
    
    return "fim"


def _deve_continuar_apos_execucao(state: HarmoniaState) -> Literal["autoavaliar", "fim"]:
    if state.get("criterio_parada_seguranca", False):
        return "fim"
    return "autoavaliar"


def _deve_continuar_apos_autoavaliacao(state: HarmoniaState) -> Literal["continuar", "pausar", "fim"]:
    if state.get("criterio_parada_seguranca", False):
        return "fim"
    
    sinais = state.get("sinais_autoavaliacao", [])
    acoes_executadas = state.get("acoes_executadas", [])
    
    if acoes_executadas and sinais:
        from datetime import datetime
        ultimo_ts = acoes_executadas[-1].get("executado_em", "")
        if ultimo_ts:
            try:
                ultimo_dt = datetime.fromisoformat(ultimo_ts)
                sinais_recentes = [
                    s for s in sinais
                    if s.get("requer_pausa") and s.get("timestamp", "") > ultimo_ts
                ]
                if sinais_recentes:
                    return "pausar"
            except (ValueError, TypeError):
                pass
    
    if not state.get("acoes_pendentes", []):
        return "fim"
    
    return "continuar"


def _deve_continuar_apos_subplano(state: HarmoniaState) -> Literal["reintegrar", "escalar", "fim"]:
    subplanos = state.get("subplanos_ativos", [])
    
    if not subplanos:
        return "fim"
    
    subplano = subplanos[-1]
    
    if subplano.get("status") == "resolvido":
        return "reintegrar"
    elif subplano.get("profundidade", 0) >= state.get("max_profundidade_subplano", 1):
        return "escalar"
    else:
        return "fim"


def compilar_sem_checkpoint() -> StateGraph:
    workflow = StateGraph(HarmoniaState)
    
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("classificar_risco", classificar_risco)
    workflow.add_node("rotear_autonomia", rotear_autonomia)
    workflow.add_node("preparar_aprovacao", preparar_aprovacao)
    workflow.add_node("aguardar_aprovacao", aguardar_aprovacao)
    workflow.add_node("executar_acao", executar_acao)
    workflow.add_node("processar_subplano", processar_subplano)
    workflow.add_node("autoavaliar", autoavaliar)
    
    workflow.set_entry_point("auditor")
    
    workflow.add_edge("auditor", "classificar_risco")
    workflow.add_edge("classificar_risco", "rotear_autonomia")
    
    workflow.add_conditional_edges(
        "rotear_autonomia",
        _deve_ir_para_aprovacao,
        {
            "aprovar": "preparar_aprovacao",
            "executar": "executar_acao",
            "subplano": "processar_subplano",
            "fim": END,
        }
    )
    
    workflow.add_edge("preparar_aprovacao", "aguardar_aprovacao")
    
    workflow.add_conditional_edges(
        "aguardar_aprovacao",
        _deve_continuar_apos_aprovacao,
        {
            "continuar": "executar_acao",
            "fim": END,
        }
    )
    
    workflow.add_edge("executar_acao", "autoavaliar")
    workflow.add_edge("processar_subplano", "autoavaliar")
    
    workflow.add_conditional_edges(
        "autoavaliar",
        _deve_continuar_apos_autoavaliacao,
        {
            "continuar": "classificar_risco",
            "pausar": END,
            "fim": END,
        }
    )
    
    return workflow


async def compilar_com_checkpoint(db_url: str | None = None):
    workflow = compilar_sem_checkpoint()
    db_url = db_url or CHECKPOINT_DB
    conn = await aiosqlite.connect(db_url)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return workflow.compile(checkpointer=checkpointer), conn


async def fechar_checkpointer():
    """Placeholder para compatibilidade - o daemon gerencia sua própria conexão."""
    pass


def criar_estado_inicial(
    plano_id: str,
    fundamentos: list[dict],
    etapas: list[dict],
    dial: str = "soninho",
) -> HarmoniaState:
    state: HarmoniaState = {
        "plano_id": plano_id,
        "dial_autonomia": dial,
        "fundamentos": [],
        "etapas": [],
        "acoes_pendentes": [],
        "acoes_executadas": [],
        "fila_aprovacao": [],
        "log_rastro": [],
        "sinais_autoavaliacao": [],
        "subplanos_ativos": [],
        "max_tentativas_mecanicas": 3,
        "max_profundidade_subplano": 1,
        "criterio_parada_seguranca": False,
        "mensagem_final": "",
        "metadata": {},
    }
    
    for f in fundamentos:
        state["fundamentos"].append(make_fundamento(
            id=f.get("id", ""),
            descricao=f.get("descricao", ""),
            prioridade=f.get("prioridade", 0),
        ))
    
    for i, e in enumerate(etapas):
        etapa = make_etapa_plano(
            id=e.get("id", ""),
            descricao=e.get("descricao", ""),
            ordem=i,
            fundamentos_ids=e.get("fundamentos_ids", []),
        )
        state["etapas"].append(etapa)
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
            )
            state["acoes_pendentes"].append(acao)
    
    return state