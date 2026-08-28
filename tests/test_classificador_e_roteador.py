from __future__ import annotations

import pytest
from harmonia.graph.state import (
    HarmoniaState, 
    AcaoProposta, 
    NivelRisco, 
    DialAutonomia,
    Fundamento,
    EtapaPlano,
    make_acao_proposta,
    make_fundamento,
)
from harmonia.nodes.classificador_risco import classificar_risco
from harmonia.nodes.roteador_autonomia import rotear_autonomia


class TestClassificadorRisco:
    
    def _estado_com_acao(self, acao: dict) -> HarmoniaState:
        return {
            "plano_id": "teste",
            "acoes_pendentes": [acao],
            "fundamentos": [],
            "etapas": [],
            "acoes_executadas": [],
            "fila_aprovacao": [],
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
    
    def test_acao_irreversivel_eh_alto_risco(self):
        acao = make_acao_proposta(
            tipo="deploy_producao",
            descricao="Deploy em producao",
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.ALTO.value
    
    def test_push_branch_protegida_eh_alto_risco(self):
        acao = make_acao_proposta(
            tipo="push_protected_branch",
            descricao="Push para main",
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.ALTO.value
    
    def test_gasto_creditos_eh_alto_risco(self):
        acao = make_acao_proposta(
            tipo="gasto_creditos",
            descricao="Gastar $50 em API",
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.ALTO.value
    
    def test_api_call_paga_eh_alto_risco(self):
        acao = make_acao_proposta(
            tipo="api_call",
            descricao="Chamar OpenAI",
            parametros={"paga": True},
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.ALTO.value
    
    def test_afeta_terceiro_eh_alto_risco(self):
        acao = make_acao_proposta(
            tipo="abrir_pr",
            descricao="Abrir PR para revisao",
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.ALTO.value
    
    def test_deploy_staging_eh_alto_risco(self):
        acao = make_acao_proposta(
            tipo="deploy",
            descricao="Deploy staging",
            parametros={"ambiente": "staging"},
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.ALTO.value
    
    def test_diverge_fundamento_eh_medio_risco(self):
        acao = make_acao_proposta(
            tipo="replanejar",
            descricao="Replanejar etapa",
            parametros={"fundamento_alterado": True},
        )
        state = self._estado_com_acao(acao)
        state["fundamentos"] = [make_fundamento(id="f1", descricao="Original")]
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.MEDIO.value
    
    def test_editar_arquivo_eh_baixo_risco(self):
        acao = make_acao_proposta(
            tipo="editar_arquivo",
            descricao="Editar arquivo local",
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.BAIXO.value
    
    def test_rodar_testes_eh_baixo_risco(self):
        acao = make_acao_proposta(
            tipo="rodar_testes",
            descricao="Rodar suite de testes",
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.BAIXO.value
    
    def test_build_local_eh_baixo_risco(self):
        acao = make_acao_proposta(
            tipo="build_local",
            descricao="Build local do projeto",
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.BAIXO.value
    
    def test_comando_readonly_eh_baixo_risco(self):
        acao = make_acao_proposta(
            tipo="comando",
            descricao="ls -la",
            parametros={"readonly": True},
        )
        state = self._estado_com_acao(acao)
        result = classificar_risco(state)
        assert result["acoes_pendentes"][0]["risco"] == NivelRisco.BAIXO.value


class TestRoteadorAutonomia:
    
    def _estado_com_acao(self, acao: dict, dial: str = "soninho") -> HarmoniaState:
        return {
            "plano_id": "teste",
            "acoes_pendentes": [acao],
            "fundamentos": [],
            "etapas": [],
            "acoes_executadas": [],
            "fila_aprovacao": [],
            "log_rastro": [],
            "sinais_autoavaliacao": [],
            "subplanos_ativos": [],
            "dial_autonomia": dial,
            "max_tentativas_mecanicas": 3,
            "max_profundidade_subplano": 1,
            "criterio_parada_seguranca": False,
            "mensagem_final": "",
            "metadata": {},
        }
    
    def test_soninho_baixo_risco_executa(self):
        acao = make_acao_proposta(tipo="editar_arquivo", descricao="Editar", risco=NivelRisco.BAIXO.value)
        state = self._estado_com_acao(acao, DialAutonomia.SONINHO.value)
        result = rotear_autonomia(state)
        assert result["acoes_pendentes"][0]["metadata"]["roteador_decisao"] == "executar"
    
    def test_soninho_medio_risco_executa(self):
        acao = make_acao_proposta(tipo="replanejar", descricao="Replanejar", risco=NivelRisco.MEDIO.value)
        state = self._estado_com_acao(acao, DialAutonomia.SONINHO.value)
        result = rotear_autonomia(state)
        assert result["acoes_pendentes"][0]["metadata"]["roteador_decisao"] == "executar"
    
    def test_soninho_alto_risco_aprova(self):
        acao = make_acao_proposta(tipo="deploy_producao", descricao="Deploy prod", risco=NivelRisco.ALTO.value)
        state = self._estado_com_acao(acao, DialAutonomia.SONINHO.value)
        result = rotear_autonomia(state)
        assert result["acoes_pendentes"][0]["metadata"]["roteador_decisao"] == "aprovar"
    
    def test_ligadao_baixo_risco_executa(self):
        acao = make_acao_proposta(tipo="editar_arquivo", descricao="Editar", risco=NivelRisco.BAIXO.value)
        state = self._estado_com_acao(acao, DialAutonomia.LIGADAO.value)
        result = rotear_autonomia(state)
        assert result["acoes_pendentes"][0]["metadata"]["roteador_decisao"] == "executar"
    
    def test_ligadao_medio_risco_aprova(self):
        acao = make_acao_proposta(tipo="replanejar", descricao="Replanejar", risco=NivelRisco.MEDIO.value)
        state = self._estado_com_acao(acao, DialAutonomia.LIGADAO.value)
        result = rotear_autonomia(state)
        assert result["acoes_pendentes"][0]["metadata"]["roteador_decisao"] == "aprovar"
    
    def test_ligadao_alto_risco_aprova(self):
        acao = make_acao_proposta(tipo="deploy_producao", descricao="Deploy prod", risco=NivelRisco.ALTO.value)
        state = self._estado_com_acao(acao, DialAutonomia.LIGADAO.value)
        result = rotear_autonomia(state)
        assert result["acoes_pendentes"][0]["metadata"]["roteador_decisao"] == "aprovar"


class TestMigracaoAutonomia:
    def setup_method(self):
        from harmonia.nodes.roteador_autonomia import reset_historico_acertos
        reset_historico_acertos()
    
    def test_categoria_migra_apos_95_porcento_acerto(self):
        from harmonia.nodes.roteador_autonomia import _registrar_acerto, _categoria_migrou_para_autonomia
        
        categoria = "baixo_editar_arquivo"
        
        for _ in range(10):
            _registrar_acerto(categoria, True)
        
        assert _categoria_migrou_para_autonomia(categoria, DialAutonomia.LIGADAO.value) == True
    
    def test_categoria_nao_migra_com_menos_de_10_tentativas(self):
        from harmonia.nodes.roteador_autonomia import _registrar_acerto, _categoria_migrou_para_autonomia
        
        categoria = "baixo_editar_arquivo"
        
        for _ in range(5):
            _registrar_acerto(categoria, True)
        
        assert _categoria_migrou_para_autonomia(categoria, DialAutonomia.LIGADAO.value) == False
    
    def test_categoria_nao_migra_no_soninho(self):
        from harmonia.nodes.roteador_autonomia import _registrar_acerto, _categoria_migrou_para_autonomia
        
        categoria = "baixo_editar_arquivo"
        
        for _ in range(20):
            _registrar_acerto(categoria, True)
        
        assert _categoria_migrou_para_autonomia(categoria, DialAutonomia.SONINHO.value) == False
