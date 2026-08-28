#!/usr/bin/env python3
"""
Integração Telegram + Harmonia Daemon.
Executa o bridge Telegram que encaminha aprovações para o daemon.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import aiohttp
from aiohttp import web

sys.path.insert(0, str(Path(__file__).parent.parent))

from harmonia.integrations.telegram_bridge import TelegramBridge, TelegramConfig, criar_bridge_do_env


class TelegramDaemonIntegration:
    def __init__(self, daemon_url: str = "http://localhost:8084"):
        self.daemon_url = daemon_url
        self.bridge: TelegramBridge | None = None
        self._session: aiohttp.ClientSession | None = None
    
    async def iniciar(self):
        # Carregar config do ambiente
        self.bridge = await criar_bridge_do_env()
        
        if not self.bridge.config.bot_token:
            print("[TELEGRAM] TELEGRAM_BOT_TOKEN não configurado. Pulando integração.")
            return
        
        if not self.bridge.config.webhook_url:
            print("[TELEGRAM] TELEGRAM_WEBHOOK_URL não configurado. Pulando integração.")
            return
        
        if not self.bridge.config.allowed_user_ids:
            print("[TELEGRAM] TELEGRAM_ALLOWED_USERS não configurado. Pulando integração.")
            return
        
        # Registrar handler que encaminha para o daemon
        self.bridge.registrar_handler_aprovacao(self._encaminhar_aprovacao)
        
        # Criar sessão HTTP para chamar daemon
        self._session = aiohttp.ClientSession()
        
        # Iniciar webhook
        ok = await self.bridge.iniciar_webhook()
        if ok:
            print(f"[TELEGRAM] Webhook registrado: {self.bridge.config.webhook_url}/webhook/<token>")
        else:
            print("[TELEGRAM] Falha ao registrar webhook")
        
        # Iniciar servidor aiohttp
        runner = web.AppRunner(self.bridge.app)
        await runner.setup()
        
        # Usar porta diferente do daemon (ex: 8443)
        port = int(os.getenv("TELEGRAM_BRIDGE_PORT", "8443"))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        
        print(f"[TELEGRAM] Bridge rodando em http://0.0.0.0:{port}")
        print(f"[TELEGRAM] Endpoint webhook: /webhook/{self.bridge.config.bot_token}")
        
        # Manter rodando
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            await runner.cleanup()
            if self._session:
                await self._session.close()
    
    async def _encaminhar_aprovacao(self, acao_id: str, aprovado: bool, user_id: int):
        """Chamado pelo bridge quando usuário clica Aprovar/Rejeitar."""
        # Buscar thread_id associado a este acao_id
        # Por enquanto, assumimos que o acao_id contém info suficiente
        # ou mantemos um mapeamento em memória
        print(f"[TELEGRAM] Aprovação recebida: acao_id={acao_id}, aprovado={aprovado}, user={user_id}")
        
        # Tentar extrair thread_id do acao_id ou usar mapeamento
        # Formato esperado: "solicitacao_id:thread_id" ou similar
        thread_id = acao_id  # fallback
        
        try:
            async with self._session.post(
                f"{self.daemon_url}/aprovar",
                json={
                    "thread_id": thread_id,
                    "resposta": {
                        "resposta": "Aprovado via Telegram" if aprovado else "Rejeitado via Telegram",
                        "aprovado": aprovado,
                        "usuario": str(user_id),
                    }
                }
            ) as resp:
                result = await resp.json()
                print(f"[TELEGRAM] Daemon response: {result}")
        except Exception as e:
            print(f"[TELEGRAM] Erro ao encaminhar para daemon: {e}")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Telegram Bridge para Harmonia Daemon")
    parser.add_argument("--daemon-url", default="http://localhost:8084", help="URL do Harmonia Daemon")
    parser.add_argument("--port", type=int, default=8443, help="Porta do bridge")
    args = parser.parse_args()
    
    integration = TelegramDaemonIntegration(daemon_url=args.daemon_url)
    await integration.iniciar()


if __name__ == "__main__":
    asyncio.run(main())