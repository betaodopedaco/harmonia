from __future__ import annotations

from unittest.mock import patch

import pytest

from harmonia.graph.state import (
    HarmoniaState,
    make_acao_proposta,
    make_solicitacao_aprovacao,
    NivelRisco,
)
from harmonia.nodes.fila_aprovacao import aguardar_aprovacao, _normalizar


class TestNormalizacao:
    def test_remove_acentos_e_minusculas(self):
        assert _normalizar("Deploy da Versão 1.2.3 em Produção") == "deploy da versao 1.2.3 em producao"

    def test_comparacao_ignora_maiusculas(self):
        assert _normalizar("DEPLOY DA VERSAO") in _normalizar("confirma: Deploy da Versão em produção")


class TestAguardarAprovacao:

    def _estado_com_aprovacao_pendente(
        self,
        acao_descricao: str = "Deploy da versao 1.2.3 em producao",
        confirmacao_qualificada: bool = True,
    ) -> HarmoniaState:
        acao = make_acao_proposta(
            tipo="deploy_producao",
            descricao=acao_descricao,
            risco=NivelRisco.ALTO.value,
            status="aguardando_aprovacao",
        )
        solicitacao = make_solicitacao_aprovacao(
            acao_id=acao["id"],
            mensagem="[APROVACAO NECESSARIA]",
            max_tentativas=3,
            prazo_validade="2099-01-01T00:00:00",
            confirmacao_qualificada=confirmacao_qualificada,
        )
        return {
            "plano_id": "teste",
            "acoes_pendentes": [acao],
            "fila_aprovacao": [solicitacao],
            "fundamentos": [],
            "etapas": [],
            "acoes_executadas": [],
            "log_rastro": [],
            "sinais_autoavaliacao": [],
            "subplanos_ativos": [],
            "dial_autonomia": "soninho",
            "max_tentativas_mecanicas": 3,
            "max_profundidade_subplano": 1,
            "criterio_parada_seguranca": False,
            "mensagem_final": "",
            "metadata": {},
        }

    def test_aprovacao_qualificada_com_resumo_correto_executa(self):
        state = self._estado_com_aprovacao_pendente(
            acao_descricao="Deploy da versao 1.2.3 em producao",
            confirmacao_qualificada=True,
        )
        with patch("harmonia.nodes.fila_aprovacao.interrupt", return_value={
            "resposta": "Deploy da versao 1.2.3 em producao",
            "aprovado": True,
        }):
            result = aguardar_aprovacao(state)

        acao = result["acoes_pendentes"][0]
        assert acao["status"] == "pendente"
        assert result["fila_aprovacao"] == []

    def test_aprovacao_qualificada_com_resumo_com_acentos_executa(self):
        state = self._estado_com_aprovacao_pendente(
            acao_descricao="Deploy da versão 1.2.3 em produção",
            confirmacao_qualificada=True,
        )
        with patch("harmonia.nodes.fila_aprovacao.interrupt", return_value={
            "resposta": "Deploy da Versão 1.2.3 em Produção",
            "aprovado": True,
        }):
            result = aguardar_aprovacao(state)

        assert result["acoes_pendentes"][0]["status"] == "pendente"
        assert result["fila_aprovacao"] == []

    def test_aprovacao_qualificada_com_resumo_errado_rejeita(self):
        """O bug critico: clique 'aprovar' que nao bate com o resumo deve REJEITAR explicitamente."""
        state = self._estado_com_aprovacao_pendente(
            acao_descricao="Deploy da versao 1.2.3 em producao",
            confirmacao_qualificada=True,
        )
        with patch("harmonia.nodes.fila_aprovacao.interrupt", return_value={
            "resposta": "aprovado via telegram",
            "aprovado": True,
        }):
            result = aguardar_aprovacao(state)

        acao = result["acoes_pendentes"][0]
        assert acao["status"] == "rejeitada"
        assert "confirmacao qualificada invalida" in result["mensagem_final"]
        assert result["fila_aprovacao"] == []

    def test_rejeicao_explicita_nao_executa_mesmo_com_resumo(self):
        """Rejeicao explicita (aprovado=False) nunca pode partir para execucao."""
        state = self._estado_com_aprovacao_pendente(
            acao_descricao="Deploy da versao 1.2.3 em producao",
            confirmacao_qualificada=True,
        )
        with patch("harmonia.nodes.fila_aprovacao.interrupt", return_value={
            "resposta": "Deploy da versao 1.2.3 em producao",
            "aprovado": False,
        }):
            result = aguardar_aprovacao(state)

        acao = result["acoes_pendentes"][0]
        assert acao["status"] == "rejeitada"
        assert "rejeitada pelo usuario" in result["mensagem_final"]

    def test_rejeicao_de_acao_nao_qualificada_nao_executa(self):
        """Bug oculto: rejeitar acao sem confirmacao qualificada antes executava. Agora rejeita."""
        state = self._estado_com_aprovacao_pendente(
            acao_descricao="Rodar migracao no banco de homologacao",
            confirmacao_qualificada=False,
        )
        with patch("harmonia.nodes.fila_aprovacao.interrupt", return_value={
            "resposta": "rejeitado",
            "aprovado": False,
        }):
            result = aguardar_aprovacao(state)

        acao = result["acoes_pendentes"][0]
        assert acao["status"] == "rejeitada"
        assert result["fila_aprovacao"] == []