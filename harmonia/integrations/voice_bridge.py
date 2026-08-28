from __future__ import annotations

import asyncio
import os
import json
from dataclasses import dataclass
from typing import Callable, Optional, Any
from datetime import datetime


@dataclass
class NVIDIAConfig:
    """Configuração para NVIDIA Riva/ASR/TTS/VoiceChat."""
    api_key: str
    base_url: str = "https://api.nvidia.com/v1"
    riva_url: str = "grpc://riva.nvidia.com:50051"  # Para Riva local/servidor
    use_voicechat: bool = True  # Usar Nemotron 3 VoiceChat (full-duplex)
    language: str = "pt-BR"
    voice_name: str = "pt-BR-Neural-Female-1"  # Ou voz clonada
    sample_rate: int = 16000


@dataclass
class TwilioConfig:
    """Configuração para Twilio (ligação telefônica real)."""
    account_sid: str
    auth_token: str
    from_number: str  # Número Twilio que faz a ligação
    to_number: str    # Seu número de destino
    webhook_url: str  # URL pública para receber webhooks do Twilio
    recording: bool = True


class NVIDIAVoiceClient:
    """
    Cliente para NVIDIA Nemotron 3 VoiceChat / Riva ASR/TTS.
    
    Referência real: NVIDIA Nemotron 3 VoiceChat (acesso antecipado)
    - ASR: Canary/Parakeet (fala → texto)
    - TTS: Riva Magpie (texto → fala)
    - VoiceChat: Full-duplex, interruptível, baixa latência
    
    Notas:
    - Alguns modelos de voz personalizada (clonagem) exigem aprovação prévia de acesso
    - VoiceChat requer conta NVIDIA e API key
    - Para produção, recomenda-se Riva self-hosted no seu servidor
    """
    
    def __init__(self, config: NVIDIAConfig):
        self.config = config
        self._session = None
    
    async def _get_session(self):
        if self._session is None:
            import aiohttp
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session
    
    async def transcrever_audio(self, audio_bytes: bytes, sample_rate: int = None) -> str:
        """
        ASR: Converte áudio (bytes) em texto.
        
        Usa endpoint NVIDIA Riva/Canary.
        """
        sample_rate = sample_rate or self.config.sample_rate
        
        # Placeholder - implementar com gRPC Riva ou HTTP API NVIDIA
        # Estrutura real:
        # response = await session.post(f"{self.config.base_url}/asr/transcribe", ...)
        
        raise NotImplementedError(
            "Implementar com NVIDIA Riva gRPC ou NVIDIA API. "
            "Ver docs: https://docs.nvidia.com/deeplearning/riva/user-guide/docs/asr/"
        )
    
    async def sintetizar_fala(self, texto: str, voice_name: str = None) -> bytes:
        """
        TTS: Converte texto em áudio (bytes).
        
        Usa Riva Magpie ou NVIDIA TTS API.
        """
        voice_name = voice_name or self.config.voice_name
        
        # Placeholder
        raise NotImplementedError(
            "Implementar com NVIDIA Riva TTS gRPC. "
            "Ver docs: https://docs.nvidia.com/deeplearning/riva/user-guide/docs/tts/"
        )
    
    async def voicechat_stream(self, audio_in_stream) -> asyncio.StreamReader:
        """
        VoiceChat full-duplex: envia áudio stream, recebe áudio stream de resposta.
        
        Nemotron 3 VoiceChat - conversa natural, interruptível.
        """
        raise NotImplementedError(
            "Implementar com NVIDIA VoiceChat WebSocket/gRPC. "
            "Acesso antecipado: https://www.nvidia.com/en-us/ai/voicechat/"
        )
    
    async def fechar(self):
        if self._session:
            await self._session.close()


class TwilioVoiceClient:
    """
    Cliente Twilio para ligações telefônicas reais.
    
    Twilio abre a chamada real (telefone toca), abre canal de áudio,
    onde o NVIDIA processa a fala dos dois lados.
    
    Fluxo:
    1. Harmonia decide "precisa aprovação por voz"
    2. Twilio.disca(to_number) → seu telefone toca
    3. Você atende → canal de áudio aberto
    4. NVIDIA ASR transcreve sua fala → Harmonia processa
    5. Harmonia responde → NVIDIA TTS fala → Twilio envia áudio pra você
    """
    
    def __init__(self, config: TwilioConfig):
        self.config = config
        self._client = None
    
    async def _get_client(self):
        if self._client is None:
            from twilio.rest import Client
            self._client = Client(self.config.account_sid, self.config.auth_token)
        return self._client
    
    async def iniciar_chamada(self, webhook_url: str = None) -> str:
        """
        Inicia ligação telefônica real.
        
        Retorna Call SID do Twilio.
        """
        client = await self._get_client()
        
        webhook = webhook_url or self.config.webhook_url
        
        call = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.calls.create(
                to=self.config.to_number,
                from_=self.config.from_number,
                url=webhook,  # TwiML que define o que acontece na chamada
                record=self.config.recording,
                recording_channels="dual",
            )
        )
        
        return call.sid
    
    async def gerar_twiml_inicio(self, mensagem_inicial: str) -> str:
        """
        Gera TwiML inicial: fala a mensagem e começa a gravar/stream.
        
        TwiML diz ao Twilio: "fale isso, depois abra stream de áudio bidirecional"
        """
        from twilio.twiml.voice_response import VoiceResponse, Start, Stream
        
        response = VoiceResponse()
        response.say(mensagem_inicial, language="pt-BR", voice="Polly.Vitoria")
        
        # Iniciar stream de mídia bidirecional para NVIDIA
        start = Start()
        stream = Stream(
            url=f"wss://{self.config.webhook_url.replace('https://', '')}/media-stream",
            track="both_tracks",
        )
        start.append(stream)
        response.append(start)
        
        return str(response)
    
    async def gerar_twiml_fala(self, texto: str) -> str:
        """Gera TwiML para falar texto via TTS."""
        from twilio.twiml.voice_response import VoiceResponse
        
        response = VoiceResponse()
        response.say(texto, language="pt-BR", voice="Polly.Vitoria")
        return str(response)
    
    async def encerrar_chamada(self, call_sid: str) -> bool:
        client = await self._get_client()
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.calls(call_sid).update(status="completed")
        )
        return True


class VoiceBridge:
    """
    Ponte de Voz: combina Twilio (ligação) + NVIDIA (ASR/TTS/VoiceChat).
    
    Este é o orquestrador que o Harmonia chama quando precisa aprovação por voz.
    """
    
    def __init__(self, twilio_config: TwilioConfig, nvidia_config: NVIDIAConfig):
        self.twilio = TwilioVoiceClient(twilio_config)
        self.nvidia = NVIDIAVoiceClient(nvidia_config)
        self._handler_aprovacao: Optional[Callable] = None
        self._chamada_ativa: Optional[str] = None
        self._media_stream_task: Optional[asyncio.Task] = None
    
    async def solicitar_aprovacao_voz(
        self,
        solicitacao_id: str,
        mensagem: str,
        confirmacao_qualificada: bool = False,
    ) -> bool:
        """
        Inicia fluxo completo de aprovação por voz:
        1. Twilio liga para você
        2. NVIDIA fala a mensagem
        3. Aguarda sua resposta falada
        4. NVIDIA transcreve → interpreta intenção → volta pro grafo
        """
        # 1. Gerar TwiML inicial
        twiml = await self.twilio.gerar_twiml_inicio(mensagem)
        
        # 2. Iniciar chamada (webhook será chamado pelo Twilio)
        call_sid = await self.twilio.iniciar_chamada()
        self._chamada_ativa = call_sid
        
        # 3. Aguardar resposta via webhook/media stream
        # O processamento real acontece no handler de webhook/media-stream
        # que alimenta NVIDIA ASR e chama _handler_aprovacao
        
        return True
    
    def registrar_handler_aprovacao(self, handler: Callable):
        """Callback chamado quando resposta de voz é processada."""
        self._handler_aprovacao = handler
    
    async def processar_media_stream(self, websocket, stream_sid: str):
        """
        Handler para WebSocket de mídia do Twilio (bidirecional).
        
        Recebe áudio do Twilio → NVIDIA ASR → intenção → resposta → NVIDIA TTS → Twilio
        """
        # Placeholder - implementar pipeline full-duplex
        # Requer: async audio buffer, VAD, streaming ASR, streaming TTS
        raise NotImplementedError(
            "Implementar pipeline WebSocket Twilio ↔ NVIDIA. "
            "Ver: https://www.twilio.com/docs/voice/media-streams"
        )
    
    async def processar_webhook_twilio(self, payload: dict) -> dict | None:
        """
        Processa webhook HTTP do Twilio (status da chamada, gravação, etc.).
        """
        event = payload.get("CallStatus") or payload.get("RecordingStatus")
        
        if event == "completed" and self._chamada_ativa:
            call_sid = payload.get("CallSid")
            if call_sid == self._chamada_ativa:
                # Chamada acabou - buscar gravação se necessário
                self._chamada_ativa = None
        
        return None
    
    async def fechar(self):
        await self.nvidia.fechar()
        if self._chamada_ativa:
            await self.twilio.encerrar_chamada(self._chamada_ativa)


async def criar_voice_bridge_do_env() -> VoiceBridge:
    """Cria VoiceBridge a partir de variáveis de ambiente."""
    twilio_config = TwilioConfig(
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        from_number=os.getenv("TWILIO_FROM_NUMBER", ""),
        to_number=os.getenv("TWILIO_TO_NUMBER", ""),
        webhook_url=os.getenv("TWILIO_WEBHOOK_URL", ""),
        recording=os.getenv("TWILIO_RECORDING", "true").lower() == "true",
    )
    
    nvidia_config = NVIDIAConfig(
        api_key=os.getenv("NVIDIA_API_KEY", ""),
        base_url=os.getenv("NVIDIA_BASE_URL", "https://api.nvidia.com/v1"),
        riva_url=os.getenv("NVIDIA_RIVA_URL", "grpc://riva.nvidia.com:50051"),
        use_voicechat=os.getenv("NVIDIA_USE_VOICECHAT", "true").lower() == "true",
        language=os.getenv("NVIDIA_LANGUAGE", "pt-BR"),
        voice_name=os.getenv("NVIDIA_VOICE_NAME", "pt-BR-Neural-Female-1"),
        sample_rate=int(os.getenv("NVIDIA_SAMPLE_RATE", "16000")),
    )
    
    return VoiceBridge(twilio_config, nvidia_config)