from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional
from harmonia.integrations.opencode_client import OpenCodeClient, criar_cliente_opencode


class IntencaoResposta(str, Enum):
    APROVAR = "aprovar"
    REJEITAR = "rejeitar"
    MAIS_DETALHES = "mais_detalhes"
    NAO_ENTENDIDO = "nao_entendido"


@dataclass
class InterpretacaoResposta:
    intencao: IntencaoResposta
    confianca: float
    texto_original: str
    resumo_extraido: str = ""
    acao_id: str = ""


class IntencaoInterpretador:
    """
    Interpreta resposta em linguagem natural (voz ou texto) -> decisao estruturada.
    
    Nao precisa de infraestrutura nova - usa o proprio modelo que ja roda o Harmonia
    (Claude, GPT, Nemotron, OpenCode) como classificador de intencao.
    
    Prompt curto: "Dado que o Harmonia perguntou X e o usuario respondeu Y, 
    isso e aprovacao, rejeicao, ou pedido de mais detalhes?"
    """
    
    def __init__(self, client: OpenCodeClient = None, model: str = None):
        self.client = client
        self.model = model
        self._prompt_cache = {}
    
    async def interpretar(
        self,
        pergunta_original: str,
        resposta_usuario: str,
        acao_id: str = "",
        contexto: dict = None,
    ) -> InterpretacaoResposta:
        """
        Classifica a resposta do usuario.
        
        Args:
            pergunta_original: O que o Harmonia perguntou (ex: mensagem de aprovacao)
            resposta_usuario: O que o usuario respondeu (voz transcrito ou texto digitado)
            acao_id: ID da acao sendo aprovada
            contexto: Info extra (risco, tipo de acao, etc.)
        
        Returns:
            InterpretacaoResposta com intencao, confianca e resumo extraido
        """
        if not self.client:
            self.client = await criar_cliente_opencode()
        
        prompt = self._construir_prompt(pergunta_original, resposta_usuario, contexto)
        
        try:
            resultado = await self.client.execute(
                prompt=prompt,
                session_title=f"intencao-{acao_id[:8]}",
                model=self.model,
                timeout=30,
            )
            
            return self._parsear_resultado(resultado, resposta_usuario, acao_id)
        
        except Exception as e:
            # Fallback heuristico se LLM falhar
            return self._fallback_heuristico(resposta_usuario, acao_id)
    
    def _construir_prompt(
        self,
        pergunta: str,
        resposta: str,
        contexto: dict = None,
    ) -> str:
        ctx = contexto or {}
        
        partes = [
            "Voce e um classificador de intencao para sistema de aprovacao humana.",
            "",
            "PERGUNTA DO HARMONIA:",
            pergunta,
            "",
            "RESPOSTA DO USUARIO:",
            resposta,
            "",
        ]
        
        if ctx.get("confirmacao_qualificada"):
            partes.extend([
                "CONTEXTO: Esta e uma aprovacao de ALTO RISCO com confirmacao qualificada.",
                "O usuario DEVE repetir o resumo da acao para confirmar que leu e entendeu.",
                "",
            ])
        
        if ctx.get("risco"):
            partes.append(f"NIVEL DE RISCO: {ctx['risco']}")
        
        partes.extend([
            "",
            "CLASSIFIQUE A INTENCAO EM UMA DESTAS CATEGORIAS:",
            "1. APROVAR - Usuario concorda explicitamente (sim, aprovado, pode ir, faca, ok, concordo, libera)",
            "2. REJEITAR - Usuario discorda explicitamente (nao, rejeito, cancela, para, nao faca, aborta)",
            "3. MAIS_DETALHES - Usuario pede mais info, questiona, quer entender melhor (por que, como, explica, detalhe, duvida)",
            "4. NAO_ENTENDIDO - Resposta ambigua, irrelevante, ou nao classificavel",
            "",
            "REGRAS:",
            "- 'Sim' sozinho = APROVAR (exceto se confirmacao qualificada)",
            "- 'Pode' / 'Pode ir' / 'Toca' = APROVAR",
            "- 'Nao' / 'Nem pensar' / 'De jeito nenhum' = REJEITAR",
            "- 'Por que?' / 'O que isso faz?' / 'Me explica' = MAIS_DETALHES",
            "- Se confirmacao qualificada: APROVAR so se usuario repetiu resumo da acao",
            "",
            "RETORNE APENAS JSON:",
            '{',
            '  "intencao": "APROVAR|REJEITAR|MAIS_DETALHES|NAO_ENTENDIDO",',
            '  "confianca": 0.0-1.0,',
            '  "resumo_extraido": "texto que usuario repetiu (se confirmacao qualificada)"',
            '}',
        ])
        
        return "\n".join(partes)
    
    def _parsear_resultado(self, resultado, resposta_original: str, acao_id: str) -> InterpretacaoResposta:
        import json
        
        try:
            # Tentar extrair JSON da resposta
            output = resultado.output.strip()
            
            # Procurar JSON na resposta
            inicio = output.find("{")
            fim = output.rfind("}") + 1
            
            if inicio >= 0 and fim > inicio:
                json_str = output[inicio:fim]
                data = json.loads(json_str)
                
                intencao_str = data.get("intencao", "NAO_ENTENDIDO").upper()
                intencao = IntencaoResposta(intencao_str) if intencao_str in IntencaoResposta.__members__ else IntencaoResposta.NAO_ENTENDIDO
                
                return InterpretacaoResposta(
                    intencao=intencao,
                    confianca=float(data.get("confianca", 0.5)),
                    texto_original=resposta_original,
                    resumo_extraido=data.get("resumo_extraido", ""),
                    acao_id=acao_id,
                )
        except Exception:
            pass
        
        return self._fallback_heuristico(resposta_original, acao_id)
    
    def _fallback_heuristico(self, resposta: str, acao_id: str) -> InterpretacaoResposta:
        """Classificador heuristico simples se LLM falhar."""
        resposta_lower = resposta.lower().strip()
        
        # Palavras-chave de aprovacao
        aprovacao_keys = ["sim", "aprovado", "pode", "pode ir", "faca", "ok", "concordo", "libera", "toca", "bora", "vamo"]
        rejeicao_keys = ["nao", "rejeito", "cancela", "para", "nao faca", "aborta", "nem pensar", "de jeito nenhum"]
        detalhes_keys = ["por que", "porque", "o que", "como", "explique", "explica", "detalhe", "duvida", "entender", "mais info"]
        
        for key in aprovacao_keys:
            if key in resposta_lower:
                return InterpretacaoResposta(
                    intencao=IntencaoResposta.APROVAR,
                    confianca=0.7,
                    texto_original=resposta,
                    acao_id=acao_id,
                )
        
        for key in rejeicao_keys:
            if key in resposta_lower:
                return InterpretacaoResposta(
                    intencao=IntencaoResposta.REJEITAR,
                    confianca=0.7,
                    texto_original=resposta,
                    acao_id=acao_id,
                )
        
        for key in detalhes_keys:
            if key in resposta_lower:
                return InterpretacaoResposta(
                    intencao=IntencaoResposta.MAIS_DETALHES,
                    confianca=0.6,
                    texto_original=resposta,
                    acao_id=acao_id,
                )
        
        return InterpretacaoResposta(
            intencao=IntencaoResposta.NAO_ENTENDIDO,
            confianca=0.3,
            texto_original=resposta,
            acao_id=acao_id,
        )


class InterpretadorConfirmacaoQualificada:
    """
    Validador especifico para confirmacao qualificada (alto risco).
    
    Verifica se o usuario REPETIU o resumo da acao apos clicar "Aprovar".
    """
    
    def __init__(self, interpretador: IntencaoInterpretador = None):
        self.interpretador = interpretador or IntencaoInterpretador()
    
    async def validar(
        self,
        resumo_esperado: str,
        resposta_usuario: str,
        acao_id: str = "",
    ) -> tuple[bool, str]:
        """
        Verifica se resposta contem o resumo esperado.
        
        Returns:
            (valido, motivo)
        """
        # Normalizar para comparacao
        esperado = resumo_esperado.lower().strip()
        recebido = resposta_usuario.lower().strip()
        
        # Verificacao direta: resumo esperado contido na resposta
        if esperado in recebido:
            return True, "Resumo conferido"
        
        # Verificacao por palavras-chave principais (pelo menos 70% das palavras)
        palavras_esperadas = set(esperado.split())
        palavras_recebidas = set(recebido.split())
        
        if not palavras_esperadas:
            return False, "Resumo esperado vazio"
        
        intersecao = palavras_esperadas & palavras_recebidas
        ratio = len(intersecao) / len(palavras_esperadas)
        
        if ratio >= 0.7:
            return True, f"Resumo conferido ({ratio:.0%} palavras)"
        
        return False, f"Resumo nao conferido (apenas {ratio:.0%} palavras coincidem)"


async def criar_interpretador_do_env() -> IntencaoInterpretador:
    """Cria interpretador usando OpenCode client do ambiente."""
    client = await criar_cliente_opencode(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    model = os.getenv("INTENCAO_MODEL", None)
    return IntencaoInterpretador(client=client, model=model)