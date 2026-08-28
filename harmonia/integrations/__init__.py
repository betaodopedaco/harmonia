# Integrations package - Harmonia

# Clientes de execução
from harmonia.integrations.opencode_client import (
    OpenCodeClient,
    OpenCodeConfig,
    ExecutionResult,
    criar_cliente_opencode,
)

from harmonia.integrations.crush_client import CrushClient
from harmonia.integrations.cao_client import CAOClient

# Canais de comunicação
from harmonia.integrations.telegram_bridge import (
    TelegramBridge,
    TelegramConfig,
    criar_bridge_do_env as criar_telegram_bridge,
)

from harmonia.integrations.whatsapp_bridge import (
    WhatsAppBridge,
    WhatsAppConfig,
    criar_bridge_do_env as criar_whatsapp_bridge,
)

from harmonia.integrations.voice_bridge import (
    VoiceBridge,
    TwilioConfig,
    NVIDIAConfig,
    TwilioVoiceClient,
    NVIDIAVoiceClient,
    criar_voice_bridge_do_env,
)

from harmonia.integrations.intencao_interpretador import (
    IntencaoInterpretador,
    InterpretadorConfirmacaoQualificada,
    IntencaoResposta,
    InterpretacaoResposta,
    criar_interpretador_do_env,
)

from harmonia.integrations.comunicacao_unificada import (
    ComunicacaoUnificada,
    ComunicacaoConfig,
    criar_comunicacao_do_env,
)

__all__ = [
    # Execução
    "OpenCodeClient",
    "OpenCodeConfig", 
    "ExecutionResult",
    "criar_cliente_opencode",
    "CrushClient",
    "CAOClient",
    
    # Telegram
    "TelegramBridge",
    "TelegramConfig",
    "criar_telegram_bridge",
    
    # WhatsApp
    "WhatsAppBridge",
    "WhatsAppConfig",
    "criar_whatsapp_bridge",
    
    # Voz
    "VoiceBridge",
    "TwilioConfig",
    "NVIDIAConfig",
    "TwilioVoiceClient",
    "NVIDIAVoiceClient",
    "criar_voice_bridge_do_env",
    
    # Intenção
    "IntencaoInterpretador",
    "InterpretadorConfirmacaoQualificada",
    "IntencaoResposta",
    "InterpretacaoResposta",
    "criar_interpretador_do_env",
    
    # Unificado
    "ComunicacaoUnificada",
    "ComunicacaoConfig",
    "criar_comunicacao_do_env",
]