from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional, TypedDict
from uuid import uuid4


class NivelRisco(str, Enum):
    BAIXO = "baixo"
    MEDIO = "medio"
    ALTO = "alto"


class StatusAcao(str, Enum):
    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    CONCLUIDA = "concluida"
    FALHOU = "falhou"
    AGUARDANDO_APROVACAO = "aguardando_aprovacao"
    REJEITADA = "rejeitada"
    EXPIRADA = "expirada"


class DialAutonomia(str, Enum):
    LIGADAO = "ligadao"
    SONINHO = "soninho"


class Fundamento(TypedDict, total=False):
    id: str
    descricao: str
    prioridade: int
    criado_em: str
    atualizado_em: str


def make_fundamento(descricao: str = "", prioridade: int = 0, **kw) -> Fundamento:
    now = datetime.now().isoformat()
    return Fundamento(
        id=kw.get("id", str(uuid4())),
        descricao=descricao,
        prioridade=prioridade,
        criado_em=kw.get("criado_em", now),
        atualizado_em=kw.get("atualizado_em", now),
    )


class AcaoProposta(TypedDict, total=False):
    id: str
    tipo: str
    descricao: str
    parametros: dict[str, Any]
    risco: str
    raciocinio: str
    impacto_estimado: str
    rollback: str
    reversivel: bool
    tentativas: int
    max_tentativas: int
    status: str
    criado_em: str
    executado_em: str
    resultado: dict[str, Any]
    erro: str
    metadata: dict[str, Any]


def make_acao_proposta(
    tipo: str = "",
    descricao: str = "",
    parametros: dict[str, Any] = None,
    risco: str = "baixo",
    raciocinio: str = "",
    impacto_estimado: str = "",
    rollback: str = None,
    reversivel: bool = True,
    max_tentativas: int = 3,
    **kw,
) -> AcaoProposta:
    return AcaoProposta(
        id=kw.get("id", str(uuid4())),
        tipo=tipo,
        descricao=descricao,
        parametros=parametros or {},
        risco=risco,
        raciocinio=raciocinio,
        impacto_estimado=impacto_estimado,
        rollback=rollback,
        reversivel=reversivel,
        tentativas=kw.get("tentativas", 0),
        max_tentativas=max_tentativas,
        status=kw.get("status", "pendente"),
        criado_em=kw.get("criado_em", datetime.now().isoformat()),
        executado_em=kw.get("executado_em"),
        resultado=kw.get("resultado"),
        erro=kw.get("erro"),
        metadata=kw.get("metadata", {}),
    )


class EtapaPlano(TypedDict, total=False):
    id: str
    descricao: str
    fundamentos_ids: list[str]
    acoes_propostas: list[AcaoProposta]
    status: str
    ordem: int


def make_etapa_plano(descricao: str = "", ordem: int = 0, **kw) -> EtapaPlano:
    return EtapaPlano(
        id=kw.get("id", str(uuid4())),
        descricao=descricao,
        fundamentos_ids=kw.get("fundamentos_ids", []),
        acoes_propostas=kw.get("acoes_propostas", []),
        status=kw.get("status", "pendente"),
        ordem=ordem,
    )


class SolicitacaoAprovacao(TypedDict, total=False):
    id: str
    acao_id: str
    mensagem: str
    tentativas_contato: int
    max_tentativas: int
    prazo_validade: str
    confirmacao_qualificada: bool
    resposta: str
    respondido_em: str
    status: str


def make_solicitacao_aprovacao(
    acao_id: str = "",
    mensagem: str = "",
    max_tentativas: int = 3,
    prazo_validade: str = None,
    confirmacao_qualificada: bool = False,
    **kw,
) -> SolicitacaoAprovacao:
    return SolicitacaoAprovacao(
        id=kw.get("id", str(uuid4())),
        acao_id=acao_id,
        mensagem=mensagem,
        tentativas_contato=kw.get("tentativas_contato", 0),
        max_tentativas=max_tentativas,
        prazo_validade=prazo_validade,
        confirmacao_qualificada=confirmacao_qualificada,
        resposta=kw.get("resposta"),
        respondido_em=kw.get("respondido_em"),
        status=kw.get("status", "pendente"),
    )


class LogRastro(TypedDict, total=False):
    id: str
    acao_id: str
    estado_antes: dict[str, Any]
    estado_depois: dict[str, Any]
    reversivel: bool
    causa: str
    timestamp: str


def make_log_rastro(
    acao_id: str = "",
    estado_antes: dict = None,
    estado_depois: dict = None,
    reversivel: bool = True,
    causa: str = "",
    **kw,
) -> LogRastro:
    return LogRastro(
        id=kw.get("id", str(uuid4())),
        acao_id=acao_id,
        estado_antes=estado_antes or {},
        estado_depois=estado_depois or {},
        reversivel=reversivel,
        causa=causa,
        timestamp=kw.get("timestamp", datetime.now().isoformat()),
    )


class SinalAutoavaliacao(TypedDict, total=False):
    id: str
    acao_id: str
    divergencia_detectada: bool
    descricao: str
    confianca: float
    requer_pausa: bool
    timestamp: str


def make_sinal_autoavaliacao(
    acao_id: str = "",
    divergencia_detectada: bool = False,
    descricao: str = "",
    confianca: float = 1.0,
    requer_pausa: bool = False,
    **kw,
) -> SinalAutoavaliacao:
    return SinalAutoavaliacao(
        id=kw.get("id", str(uuid4())),
        acao_id=acao_id,
        divergencia_detectada=divergencia_detectada,
        descricao=descricao,
        confianca=confianca,
        requer_pausa=requer_pausa,
        timestamp=kw.get("timestamp", datetime.now().isoformat()),
    )


class Subplano(TypedDict, total=False):
    id: str
    acao_origem_id: str
    fundamento_divergente_id: str
    descricao: str
    acoes: list[AcaoProposta]
    profundidade: int
    status: str
    criado_em: str
    resolvido_em: str


def make_subplano(
    acao_origem_id: str = "",
    fundamento_divergente_id: str = "",
    descricao: str = "",
    profundidade: int = 0,
    **kw,
) -> Subplano:
    return Subplano(
        id=kw.get("id", str(uuid4())),
        acao_origem_id=acao_origem_id,
        fundamento_divergente_id=fundamento_divergente_id,
        descricao=descricao,
        acoes=kw.get("acoes", []),
        profundidade=profundidade,
        status=kw.get("status", "ativo"),
        criado_em=kw.get("criado_em", datetime.now().isoformat()),
        resolvido_em=kw.get("resolvido_em"),
    )


class HarmoniaState(TypedDict, total=False):
    plano_id: str
    fundamentos: list[Fundamento]
    etapas: list[EtapaPlano]
    acoes_pendentes: list[AcaoProposta]
    acoes_executadas: list[AcaoProposta]
    fila_aprovacao: list[SolicitacaoAprovacao]
    log_rastro: list[LogRastro]
    sinais_autoavaliacao: list[SinalAutoavaliacao]
    subplanos_ativos: list[Subplano]
    dial_autonomia: str
    max_tentativas_mecanicas: int
    max_profundidade_subplano: int
    criterio_parada_seguranca: bool
    mensagem_final: str
    metadata: dict[str, Any]
