from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional, Any

from harmonia.graph.state import SolicitacaoAprovacao, NivelRisco
from harmonia.integrations.telegram_bridge import TelegramBridge, TelegramConfig
from harmonia.integrations.whatsapp_bridge import WhatsAppBridge, WhatsAppConfig
from harmonia.integrations.voice_bridge import VoiceBridge, TwilioConfig, NVIDIAConfig
from harmonia.integrations.intencao_interpretador import (
    IntencaoInterpretador,
    InterpretadorConfirmacaoQualificada,
    IntencaoResposta,
)


@dataclass
class ComunicacaoConfig:
    """Configuração unificada para todos os canais de comunicação."""
    # Telegram (já existente)
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""
    telegram_secret_token: str = ""
    telegram_allowed_users: list[int] = None
    
    # WhatsApp (novo - Baileys)
    whatsapp_enabled: bool = False
    whatsapp_session_name: str = "harmonia"
    whatsapp_baileys_port: int = 3001
    whatsapp_baileys_host: str = "localhost"
    whatsapp_webhook_url: str = ""
    whatsapp_secret_token: str = ""
    whatsapp_allowed_numbers: list[str] = None
    whatsapp_session_dir: str = "./whatsapp_session"
    
    # Voz (novo - Twilio + NVIDIA)
    voice_enabled: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    twilio_to_number: str = ""
    twilio_webhook_url: str = ""
    twilio_recording: bool = True
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://api.nvidia.com/v1"
    nvidia_riva_url: str = "grpc://riva.nvidia.com:50051"
    nvidia_use_voicechat: bool = True
    nvidia_language: str = "pt-BR"
    nvidia_voice_name: str = "pt-BR-Neural-Female-1"
    nvidia_sample_rate: int = 16000
    
    # Interpretador de intenção
    intencao_model: str = ""


class ComunicacaoUnificada:
    """
    Orquestrador único para todos os canais de comunicação do Harmonia.
    
    O grafo LangGraph (fila_aprovacao) chama este bridge único.
    Ele decide qual canal usar baseado em:
    - Configuração habilitada
    - Nível de risco (alto = voz + texto, médio/baixo = texto)
    - Preferência do usuário (dial Ligadão/Soninho)
    
    Canais disponíveis:
    1. Telegram (webhook, botões inline, confirmação qualificada)
    2. WhatsApp (Baileys self-hosted, botões, número dedicado)
    3. Voz (Twilio liga real + NVIDIA ASR/TTS/VoiceChat)
    
    Todos compartilham o mesmo contrato de dados:
    - enviar_solicitacao_aprovacao(solicitacao_id, mensagem, confirmacao_qualificada)
    - processar_webhook(payload) -> dict padronizado
    - registrar_handler_aprovacao(callback)
    """
    
    def __init__(self, config: ComunicacaoConfig):
        self.config = config
        self.telegram: Optional[TelegramBridge] = None
        self.whatsapp: Optional[WhatsAppBridge] = None
        self.voice: Optional[VoiceBridge] = None
        self.intencao: Optional[IntencaoInterpretador] = None
        self.confirmacao_qualificada: Optional[InterpretadorConfirmacaoQualificada] = None
        self._handler_aprovacao: Optional[Callable] = None
        self._solicitacoes_pendentes: dict[str, dict] = {}  # solicitacao_id -> info
    
    async def inicializar(self):
        """Inicializa todos os canais habilitados."""
        # Telegram
        if self.config.telegram_enabled and self.config.telegram_bot_token:
            self.telegram = TelegramBridge(TelegramConfig(
                bot_token=self.config.telegram_bot_token,
                webhook_url=self.config.telegram_webhook_url,
                secret_token=self.config.telegram_secret_token,
                allowed_user_ids=self.config.telegram_allowed_users or [],
            ))
            self.telegram.registrar_handler_aprovacao(self._on_aprovacao_recebida)
            # Servidor webhook roda separado (ver rodar_servidores())
        
        # WhatsApp
        if self.config.whatsapp_enabled:
            self.whatsapp = WhatsAppBridge(WhatsAppConfig(
                session_name=self.config.whatsapp_session_name,
                baileys_port=self.config.whatsapp_baileys_port,
                baileys_host=self.config.whatsapp_baileys_host,
                webhook_url=self.config.whatsapp_webhook_url,
                secret_token=self.config.whatsapp_secret_token,
                allowed_numbers=self.config.whatsapp_allowed_numbers or [],
                session_dir=self.config.whatsapp_session_dir,
            ))
            self.whatsapp.registrar_handler_aprovacao(self._on_aprovacao_recebida)
            await self.whatsapp.iniciar_baileys()
        
        # Voz
        if self.config.voice_enabled and self.config.twilio_account_sid and self.config.nvidia_api_key:
            self.voice = VoiceBridge(
                TwilioConfig(
                    account_sid=self.config.twilio_account_sid,
                    auth_token=self.config.twilio_auth_token,
                    from_number=self.config.twilio_from_number,
                    to_number=self.config.twilio_to_number,
                    webhook_url=self.config.twilio_webhook_url,
                    recording=self.config.twilio_recording,
                ),
                NVIDIAConfig(
                    api_key=self.config.nvidia_api_key,
                    base_url=self.config.nvidia_base_url,
                    riva_url=self.config.nvidia_riva_url,
                    use_voicechat=self.config.nvidia_use_voicechat,
                    language=self.config.nvidia_language,
                    voice_name=self.config.nvidia_voice_name,
                    sample_rate=self.config.nvidia_sample_rate,
                )
            )
            self.voice.registrar_handler_aprovacao(self._on_aprovacao_recebida)
        
        # Interpretador de intenção (para voz e texto livre)
        self.intencao = IntencaoInterpretador(model=self.config.intencao_model or None)
        self.confirmacao_qualificada = InterpretadorConfirmacaoQualificada(self.intencao)
    
    def registrar_handler_aprovacao(self, handler: Callable):
        """Callback global quando qualquer canal recebe aprovação/rejeição."""
        self._handler_aprovacao = handler
    
    async def enviar_solicitacao_aprovacao(
        self,
        solicitacao: SolicitacaoAprovacao,
        mensagem: str,
        risco: NivelRisco,
        confirmacao_qualificada: bool = False,
    ) -> bool:
        """
        Envia solicitação por TODOS os canais habilitados.
        
        Para ALTO risco: usa Voz + WhatsApp + Telegram (redundância)
        Para MÉDIO/BAIXO: usa WhatsApp + Telegram (texto)
        
        Retorna True se pelo menos um canal enviou com sucesso.
        """
        self._solicitacoes_pendentes[solicitacao.id] = {
            "acao_id": solicitacao.acao_id,
            "risco": risco,
            "confirmacao_qualificada": confirmacao_qualificada,
            "resumo_esperado": solicitacao.acao_id[:100] if confirmacao_qualificada else "",
        }
        
        sucessos = []
        
        # Sempre tenta Telegram se habilitado
        if self.telegram:
            try:
                ok = await self.telegram.enviar_solicitacao_aprovacao(
                    solicitacao.id, mensagem, confirmacao_qualificada
                )
                sucessos.append(("telegram", ok))
            except Exception as e:
                print(f"[ComunicacaoUnificada] Erro Telegram: {e}")
                sucessos.append(("telegram", False))
        
        # WhatsApp para todos os riscos
        if self.whatsapp:
            try:
                ok = await self.whatsapp.enviar_solicitacao_aprovacao(
                    solicitacao.id, mensagem, confirmacao_qualificada
                )
                sucessos.append(("whatsapp", ok))
            except Exception as e:
                print(f"[ComunicacaoUnificada] Erro WhatsApp: {e}")
                sucessos.append(("whatsapp", False))
        
        # Voz APENAS para alto risco (reduz custo/complexidade)
        if self.voice and risco == NivelRisco.ALTO:
            try:
                ok = await self.voice.solicitar_aprovacao_voz(
                    solicitacao.id, mensagem, confirmacao_qualificada
                )
                sucessos.append(("voice", ok))
            except Exception as e:
                print(f"[ComunicacaoUnificada] Erro Voice: {e}")
                sucessos.append(("voice", False))
        
        # Log
        for canal, ok in sucessos:
            status = "✅" if ok else "❌"
            print(f"[ComunicacaoUnificada] {status} {canal}: {'enviado' if ok else 'falhou'}")
        
        return any(ok for _, ok in sucessos)
    
    async def enviar_imagem_relatorio(self, caminho_imagem: str, legenda: str) -> bool:
        """Envia relatório/imagem por canais de texto (WhatsApp + Telegram)."""
        sucessos = []
        
        if self.telegram:
            try:
                # TelegramBridge não tem enviar_imagem implementado ainda
                # Adicionar se necessário
                pass
            except Exception:
                pass
        
        if self.whatsapp:
            try:
                ok = await self.whatsapp.enviar_imagem_relatorio(caminho_imagem, legenda)
                sucessos.append(("whatsapp", ok))
            except Exception:
                pass
        
        return any(ok for _, ok in sucessos)
    
    async def _on_aprovacao_recebida(self, acao_id: str, aprovado: bool, origem: str):
        """Callback interno quando qualquer canal recebe resposta."""
        # Buscar info da solicitação pendente
        info = None
        for sol_id, sol_info in self._solicitacoes_pendentes.items():
            if sol_info["acao_id"] == acao_id:
                info = sol_info
                break
        
        confirmacao_ok = True
        motivo = ""
        
        # Se alto risco e confirmacao_qualificada, validar
        if info and info.get("confirmacao_qualificada") and aprovado:
            # Para voz/texto livre, precisa interpretar a resposta
            # Aqui assumimos que o callback já traz a resposta processada
            # Se for botão (Telegram/WhatsApp), validar depois via mensagem de texto
            pass
        
        # Chamar handler global
        if self._handler_aprovacao:
            await self._handler_aprovacao(acao_id, aprovado and confirmacao_ok, origem, motivo)
        
        # Limpar solicitação pendente
        if info:
            for sol_id, sol_info in list(self._solicitacoes_pendentes.items()):
                if sol_info["acao_id"] == acao_id:
                    del self._solicitacoes_pendentes[sol_id]
                    break
    
    async def processar_webhook(self, canal: str, payload: dict) -> dict | None:
        """
        Processa webhook de qualquer canal e normaliza resposta.
        
        Canais: "telegram", "whatsapp", "voice", "twilio"
        """
        if canal == "telegram" and self.telegram:
            return await self.telegram._webhook_handler(payload)  # type: ignore
        
        elif canal == "whatsapp" and self.whatsapp:
            resultado = await self.whatsapp.processar_webhook(payload)
            if resultado and resultado["tipo"] == "mensagem" and self.intencao:
                # Texto livre no WhatsApp - interpretar intenção
                info = self._buscar_solicitacao_por_origem(origem="whatsapp")
                if info:
                    interpretacao = await self.intencao.interpretar(
                        pergunta_original="",  # Seria ideal ter a pergunta original
                        resposta_usuario=resultado["text"],
                        acao_id=info["acao_id"],
                        contexto={"confirmacao_qualificada": info.get("confirmacao_qualificada", False)},
                    )
                    return {
                        "tipo": "aprovacao",
                        "acao_id": info["acao_id"],
                        "aprovado": interpretacao.intencao == IntencaoResposta.APROVAR,
                        "intencao": interpretacao.intencao.value,
                        "confianca": interpretacao.confianca,
                    }
            return resultado
        
        elif canal == "voice" and self.voice:
            return await self.voice.processar_webhook_twilio(payload)
        
        elif canal == "twilio" and self.voice:
            return await self.voice.processar_webhook_twilio(payload)
        
        return None
    
    def _buscar_solicitacao_por_origem(self, origem: str) -> Optional[dict]:
        """Busca solicitação pendente mais recente."""
        for sol_info in reversed(list(self._solicitacoes_pendentes.values())):
            return sol_info
        return None
    
    async def processar_resposta_texto_livre(
        self,
        acao_id: str,
        texto: str,
        confirmacao_qualificada: bool = False,
    ) -> tuple[bool, str]:
        """
        Processa resposta em texto livre (WhatsApp digitado, voz transcrito).
        
        Returns:
            (aprovado, motivo)
        """
        if not self.intencao:
            return False, "Interpretador não inicializado"
        
        info = self._buscar_solicitacao_por_origem("")
        
        interpretacao = await self.intencao.interpretar(
            pergunta_original="",  # Ideal ter armazenado
            resposta_usuario=texto,
            acao_id=acao_id,
            contexto={"confirmacao_qualificada": confirmacao_qualificada},
        )
        
        if interpretacao.intencao == IntencaoResposta.NAO_ENTENDIDO:
            return False, "Não entendi. Responda 'aprovo', 'rejeito' ou peça detalhes."
        
        if interpretacao.intencao == IntencaoResposta.MAIS_DETALHES:
            return False, "MAIS_DETALHES"  # Sinal especial para reenviar info
        
        if interpretacao.intencao == IntencaoResposta.REJEITAR:
            return False, "Rejeitado pelo usuário"
        
        # APROVAR
        if confirmacao_qualificada:
            valido, motivo = await self.confirmacao_qualificada.validar(
                info.get("resumo_esperado", "") if info else "",
                texto,
                acao_id,
            )
            if not valido:
                return False, f"Confirmação qualificada falhou: {motivo}"
            return True, "Aprovado com confirmação qualificada"
        
        return True, "Aprovado"
    
    async def rodar_servidores(self):
        """Inicia servidores webhook (Telegram, etc.) - roda para sempre."""
        tasks = []
        
        if self.telegram:
            tasks.append(self.telegram.rodar_servidor())
        
        # WhatsApp e Voice usam webhooks HTTP - precisam servidor separado (aiohttp/FastAPI)
        # Não implementado aqui - usar uvicorn/fastapi para expor /webhook endpoints
        
        if tasks:
            await asyncio.gather(*tasks)
    
    async def fechar(self):
        """Fecha todos os canais."""
        if self.telegram:
            # TelegramBridge não tem fechar explícito
            pass
        if self.whatsapp:
            await self.whatsapp.fechar()
        if self.voice:
            await self.voice.fechar()
        if self.intencao and self.intencao.client:
            await self.intencao.client.close()


async def criar_comunicacao_do_env() -> ComunicacaoUnificada:
    """Cria ComunicacaoUnificada a partir de variáveis de ambiente."""
    import os
    
    config = ComunicacaoConfig(
        # Telegram
        telegram_enabled=os.getenv("TELEGRAM_ENABLED", "false").lower() == "true",
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_webhook_url=os.getenv("TELEGRAM_WEBHOOK_URL", ""),
        telegram_secret_token=os.getenv("TELEGRAM_SECRET_TOKEN", ""),
        telegram_allowed_users=[int(x) for x in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if x],
        
        # WhatsApp
        whatsapp_enabled=os.getenv("WHATSAPP_ENABLED", "false").lower() == "true",
        whatsapp_session_name=os.getenv("WHATSAPP_SESSION_NAME", "harmonia"),
        whatsapp_baileys_port=int(os.getenv("WHATSAPP_BAILEYS_PORT", "3001")),
        whatsapp_baileys_host=os.getenv("WHATSAPP_BAILEYS_HOST", "localhost"),
        whatsapp_webhook_url=os.getenv("WHATSAPP_WEBHOOK_URL", ""),
        whatsapp_secret_token=os.getenv("WHATSAPP_SECRET_TOKEN", ""),
        whatsapp_allowed_numbers=[x.strip() for x in os.getenv("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if x.strip()],
        whatsapp_session_dir=os.getenv("WHATSAPP_SESSION_DIR", "./whatsapp_session"),
        
        # Voz
        voice_enabled=os.getenv("VOICE_ENABLED", "false").lower() == "true",
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_from_number=os.getenv("TWILIO_FROM_NUMBER", ""),
        twilio_to_number=os.getenv("TWILIO_TO_NUMBER", ""),
        twilio_webhook_url=os.getenv("TWILIO_WEBHOOK_URL", ""),
        twilio_recording=os.getenv("TWILIO_RECORDING", "true").lower() == "true",
        nvidia_api_key=os.getenv("NVIDIA_API_KEY", ""),
        nvidia_base_url=os.getenv("NVIDIA_BASE_URL", "https://api.nvidia.com/v1"),
        nvidia_riva_url=os.getenv("NVIDIA_RIVA_URL", "grpc://riva.nvidia.com:50051"),
        nvidia_use_voicechat=os.getenv("NVIDIA_USE_VOICECHAT", "true").lower() == "true",
        nvidia_language=os.getenv("NVIDIA_LANGUAGE", "pt-BR"),
        nvidia_voice_name=os.getenv("NVIDIA_VOICE_NAME", "pt-BR-Neural-Female-1"),
        nvidia_sample_rate=int(os.getenv("NVIDIA_SAMPLE_RATE", "16000")),
        
        # Intent
        intencao_model=os.getenv("INTENCAO_MODEL", ""),
    )
    
    comm = ComunicacaoUnificada(config)
    await comm.inicializar()
    return comm