from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional
from aiohttp import web
import aiohttp


@dataclass
class TelegramConfig:
    bot_token: str
    webhook_url: str
    secret_token: str = ""
    allowed_user_ids: list[int] = None


class TelegramBridge:
    """
    Ponte Telegram para aprovações Ligadão/Soninho.
    
    Mesmo canal para ambos - só muda o limiar de quando dispara (dial).
    
    Usa webhook (não polling) - push instantâneo, requer HTTPS + endpoint público.
    Let's Encrypt para certificado grátis.
    
    Formato da mensagem de aprovação:
    - Botão inline "Aprovar" / "Rejeitar"
    - Para alto risco: exige resposta digitando resumo (confirmação qualificada)
    """
    
    def __init__(self, config: TelegramConfig):
        self.config = config
        self.app = web.Application()
        self._handler_aprovacao: Optional[Callable] = None
        self._setup_routes()
    
    def _setup_routes(self):
        self.app.router.add_post(f"/webhook/{self.config.bot_token}", self._webhook_handler)
        self.app.router.add_get("/health", self._health_handler)
    
    async def _health_handler(self, request):
        return web.json_response({"status": "ok"})
    
    async def _webhook_handler(self, request):
        try:
            update = await request.json()
            
            if "callback_query" in update:
                await self._processar_callback(update["callback_query"])
            elif "message" in update:
                await self._processar_mensagem(update["message"])
            
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)
    
    async def _processar_callback(self, callback_query: dict):
        data = callback_query.get("data", "")
        user_id = callback_query["from"]["id"]
        message_id = callback_query["message"]["message_id"]
        chat_id = callback_query["message"]["chat"]["id"]
        
        if self.config.allowed_user_ids and user_id not in self.config.allowed_user_ids:
            await self._responder_callback(callback_query["id"], "Não autorizado", show_alert=True)
            return
        
        if data.startswith("aprovar:") or data.startswith("rejeitar:"):
            acao_id = data.split(":", 1)[1]
            aprovado = data.startswith("aprovar:")
            
            if self._handler_aprovacao:
                await self._handler_aprovacao(acao_id, aprovado, user_id)
            
            texto = "✅ Aprovado" if aprovado else "❌ Rejeitado"
            await self._editar_mensagem(chat_id, message_id, texto)
            await self._responder_callback(callback_query["id"], texto)
    
    async def _processar_mensagem(self, message: dict):
        user_id = message["from"]["id"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "")
        
        if self.config.allowed_user_ids and user_id not in self.config.allowed_user_ids:
            await self._enviar_mensagem(chat_id, "Não autorizado")
            return
        
        if text.startswith("/start"):
            await self._enviar_mensagem(chat_id, "Harmonia Bridge ativo. Aguardando aprovações...")
    
    def registrar_handler_aprovacao(self, handler: Callable):
        self._handler_aprovacao = handler
    
    async def _responder_callback(self, callback_query_id: str, texto: str, show_alert: bool = False):
        url = f"https://api.telegram.org/bot{self.config.bot_token}/answerCallbackQuery"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={
                "callback_query_id": callback_query_id,
                "text": texto,
                "show_alert": show_alert,
            })
    
    async def _editar_mensagem(self, chat_id: int, message_id: int, texto: str):
        url = f"https://api.telegram.org/bot{self.config.bot_token}/editMessageText"
        async with aiohttp.ClientSession() as session:
            await session.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": texto,
            })
    
    async def enviar_solicitacao_aprovacao(
        self, 
        solicitacao_id: str,
        mensagem: str,
        confirmacao_qualificada: bool = False,
    ) -> bool:
        """
        Envia solicitação de aprovação via Telegram com botões inline.
        
        Para alto risco (confirmacao_qualificada=True): 
        - Botão "Aprovar" exige resposta digitando resumo depois
        """
        chat_id = self.config.allowed_user_ids[0] if self.config.allowed_user_ids else None
        if not chat_id:
            return False
        
        botoes = {
            "inline_keyboard": [[
                {"text": "✅ Aprovar", "callback_data": f"aprovar:{solicitacao_id}"},
                {"text": "❌ Rejeitar", "callback_data": f"rejeitar:{solicitacao_id}"},
            ]]
        }
        
        if confirmacao_qualificada:
            mensagem += "\n\n⚠️ **Confirmação qualificada:** Após clicar 'Aprovar', digite o resumo da ação para confirmar."
        
        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        async with aiohttp.ClientSession() as session:
            resp = await session.post(url, json={
                "chat_id": chat_id,
                "text": mensagem,
                "parse_mode": "Markdown",
                "reply_markup": botoes,
            })
            return resp.status == 200
    
    async def iniciar_webhook(self):
        url = f"https://api.telegram.org/bot{self.config.bot_token}/setWebhook"
        webhook_full = f"{self.config.webhook_url}/webhook/{self.config.bot_token}"
        
        async with aiohttp.ClientSession() as session:
            resp = await session.post(url, json={
                "url": webhook_full,
                "secret_token": self.config.secret_token,
                "allowed_updates": ["message", "callback_query"],
            })
            return resp.status == 200
    
    async def rodar_servidor(self, host: str = "0.0.0.0", port: int = 8443):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        print(f"Telegram Bridge rodando em https://{host}:{port}")
        
        await self.iniciar_webhook()
        
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            await runner.cleanup()


async def criar_bridge_do_env() -> TelegramBridge:
    import os
    config = TelegramConfig(
        bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        webhook_url=os.getenv("TELEGRAM_WEBHOOK_URL", ""),
        secret_token=os.getenv("TELEGRAM_SECRET_TOKEN", ""),
        allowed_user_ids=[int(x) for x in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if x],
    )
    return TelegramBridge(config)