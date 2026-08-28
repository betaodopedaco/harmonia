#!/usr/bin/env python3
"""
Bot Telegram do Harmonia - Polling mode + Ligadão.

Modos:
- Soninho: aprovações via daemon (existente)
- Ligadão: ponte direta OpenCode ↔ Telegram (texto livre, stream, permissões)
"""
from __future__ import annotations

import asyncio
import os
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

import aiohttp
import httpx
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DAEMON_URL = os.getenv("DAEMON_URL", "http://localhost:8081")
OPENCODE_URL = os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096")
OPENCODE_PASSWORD = os.getenv("OPENCODE_SERVER_PASSWORD", "")
ALLOWED_USERS = [int(x) for x in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if x.strip()]
PROJECT_ROOT = Path(__file__).parent.parent
CHAT_ID_FILE = PROJECT_ROOT / ".telegram_chat_id"

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

_offset = 0

# Aguardando confirmacao qualificada (Soninho): chat_id -> {thread_id, solicitacao_id, descricao_norm}
_aguardando_qualificacao: dict[int, dict] = {}

# Ligadão: chat_id -> OpenCodeClient ativo
_ligado_sessions: dict[int, "LigadoSession"] = {}


def _normalizar(texto: str) -> str:
    """Remove acentos, minusculas e pontuacao. Mesma normalizacao do graph."""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


async def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API_BASE}/sendMessage", json=payload)


async def answer_callback(callback_id: str, text: str, show_alert: bool = False):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API_BASE}/answerCallbackQuery", json={
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": show_alert,
        })


async def edit_message(chat_id: int, message_id: int, text: str):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API_BASE}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        })


async def call_daemon_aprovar(thread_id: str, resposta: dict) -> dict:
    async with aiohttp.ClientSession() as s:
        resp = await s.post(f"{DAEMON_URL}/aprovar", json={
            "thread_id": thread_id,
            "resposta": resposta,
        })
        return await resp.json()


async def call_daemon_status(thread_id: str) -> dict:
    async with aiohttp.ClientSession() as s:
        resp = await s.get(f"{DAEMON_URL}/status/{thread_id}")
        return await resp.json()


async def handle_callback_query(cq: dict):
    user_id = cq["from"]["id"]
    data = cq.get("data", "")
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await answer_callback(cq["id"], "Não autorizado", show_alert=True)
        return

    # Ligadão: permissões do OpenCode
    if data.startswith("ligado_perm:"):
        await _handle_ligado_permission(cq, data)
        return

    # Soninho: aprovações do daemon
    if data.startswith("aprovar:") or data.startswith("rejeitar:"):
        await _handle_soninho_aprovacao(cq, data)
        return


async def _handle_ligado_permission(cq: dict, data: str):
    """Trata callback de permissão do Ligadão: ligado_perm:{chat_id}:{permission_id}:{allow|deny}"""
    parts = data.split(":", 3)
    if len(parts) < 4:
        await answer_callback(cq["id"], "Dados inválidos", show_alert=True)
        return
    
    target_chat_id = int(parts[1])
    permission_id = parts[2]
    allow = parts[3] == "allow"
    
    session = _ligado_sessions.get(target_chat_id)
    if not session or not session.client or not session.session_id:
        await answer_callback(cq["id"], "Sessão não encontrada", show_alert=True)
        return
    
    try:
        resp = await session.client.post(
            f"/session/{session.session_id}/permissions/{permission_id}",
            json={"response": "allow" if allow else "deny", "remember": False},
            timeout=httpx.Timeout(30.0),
        )
        resp.raise_for_status()
        acao = "permitida" if allow else "negada"
        await edit_message(cq["message"]["chat"]["id"], cq["message"]["message_id"],
            f"✅ Permissão {acao}. OpenCode continua...")
        await answer_callback(cq["id"], f"Permissão {acao}")
        print(f"[LIGADÃO] Permissão {permission_id} {'permitida' if allow else 'negada'} para chat {target_chat_id}")
    except Exception as e:
        await answer_callback(cq["id"], f"Erro: {e}", show_alert=True)


async def _handle_soninho_aprovacao(cq: dict, data: str):
    user_id = cq["from"]["id"]
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await answer_callback(cq["id"], "Não autorizado", show_alert=True)
        return

    if data.startswith("aprovar:"):
        parts = data.split(":", 2)
        sol_id = parts[1] if len(parts) > 1 else ""
        thread_id = parts[2] if len(parts) > 2 else ""

        if not thread_id:
            await answer_callback(cq["id"], "Solicitacao expirada", show_alert=True)
            return

        status_info = await call_daemon_status(thread_id)
        solicitacao = status_info.get("solicitacao", {})
        qualificada = solicitacao.get("confirmacao_qualificada", False)

        if qualificada:
            descricao = solicitacao.get("acao_descricao", "")
            if not descricao:
                await answer_callback(cq["id"], "Não foi possivel obter a acao", show_alert=True)
                return

            _aguardando_qualificacao[chat_id] = {
                "thread_id": thread_id,
                "solicitacao_id": sol_id,
                "descricao_norm": _normalizar(descricao),
            }
            await edit_message(chat_id, message_id,
                f"⚠️ Confirmação qualificada necessária.\n\n"
                f"Digite (ou cole) o resumo da ação abaixo para confirmar que leu e entendeu:\n\n"
                f"`{descricao}`")
            await answer_callback(cq["id"], "Digite o resumo da ação para confirmar")
        else:
            result = await call_daemon_aprovar(thread_id, {
                "resposta": "aprovado",
                "aprovado": True,
                "usuario": user_id,
            })
            status = result.get("status", "desconhecido")
            await edit_message(chat_id, message_id, f"✅ Aprovado! Status: {status}")
            await answer_callback(cq["id"], f"Aprovado - {status}")

    elif data.startswith("rejeitar:"):
        parts = data.split(":", 2)
        sol_id = parts[1] if len(parts) > 1 else ""
        thread_id = parts[2] if len(parts) > 2 else ""

        if not thread_id:
            await answer_callback(cq["id"], "Solicitacao expirada", show_alert=True)
            return

        result = await call_daemon_aprovar(thread_id, {
            "resposta": "rejeitado",
            "aprovado": False,
            "usuario": user_id,
        })

        status = result.get("status", "desconhecido")
        await edit_message(chat_id, message_id, f"❌ Rejeitado! Status: {status}")
        await answer_callback(cq["id"], f"Rejeitado - {status}")


async def handle_message(msg: dict):
    user_id = msg["from"]["id"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")

    if text == "/start":
        CHAT_ID_FILE.write_text(str(chat_id))
        await send_message(chat_id, f"🤖 Harmonia Bot ativo.\nChat ID: {chat_id}\nModos:\n/ligado - entra no modo Ligadão (ponte OpenCode)\n/soninho - modo auditor (padrão)\n/status - saúde do daemon")
        print(f"[TELEGRAM BOT] Chat ID salvo: {chat_id}")
        return

    if chat_id in _aguardando_qualificacao:
        await _processar_confirmacao_qualificada(user_id, chat_id, text)
        return

    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        await send_message(chat_id, "Não autorizado.")
        return

    # Comandos
    if text == "/ligado":
        await _entrar_ligado(chat_id)
        return
    
    if text == "/soninho":
        await _sair_ligado(chat_id)
        await send_message(chat_id, "😴 Modo Soninho ativo. Auditor monitorando...")
        return
    
    if text == "/status":
        async with aiohttp.ClientSession() as s:
            resp = await s.get(f"{DAEMON_URL}/health")
            data = await resp.json()
        await send_message(chat_id, f"Daemon: {data}")
        return

    # Ligadão ativo: texto livre = prompt pro OpenCode
    if chat_id in _ligado_sessions:
        await _ligado_enviar_prompt(chat_id, text)
        return

    # Soninho (padrão): só comandos
    await send_message(chat_id, "Comandos: /start /ligado /soninho /status")


class LigadoSession:
    """Sessão Ligadão para um chat: HTTP direto no OpenCode (sem SSE)."""
    
    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self.client: Optional[httpx.AsyncClient] = None
        self.session_id: Optional[str] = None
        self.last_message_id: Optional[int] = None
    
    async def start(self):
        self.client = httpx.AsyncClient(
            base_url=OPENCODE_URL,
            timeout=httpx.Timeout(120.0),
        )
        
        # Verificar saúde
        resp = await self.client.get("/global/health")
        resp.raise_for_status()
        print(f"[LIGADÃO] OpenCode saudável: {resp.json()}")
        
        # Criar sessão
        resp = await self.client.post(
            "/session",
            json={"title": f"ligado-{datetime.now().strftime('%Y%m%d-%H%M%S')}"},
        )
        resp.raise_for_status()
        self.session_id = resp.json()["id"]
        print(f"[LIGADÃO] Sessão criada: {self.session_id}")
        
        await send_message(self.chat_id, "⚡ **Modo Ligadão ativo**\n\nMande qualquer texto pro OpenCode.\nUse /soninho para sair.")
        print(f"[LIGADÃO] Chat {self.chat_id} entrou no modo Ligadão")
    
    async def send_prompt(self, prompt: str):
        if not self.client or not self.session_id:
            return
        
        model_payload = {
            "modelID": "nemotron-3-ultra-free",
            "providerID": "opencode",
            "variant": "default"
        }
        
        try:
            resp = await self.client.post(
                f"/session/{self.session_id}/message",
                json={
                    "parts": [{"type": "text", "text": prompt}],
                    "model": model_payload,
                },
                timeout=httpx.Timeout(120.0),
            )
            
            if resp.status_code != 200:
                text = resp.text
                await self._send_or_edit(f"❌ Erro OpenCode ({resp.status_code}): {text}")
                return
            
            result = resp.json()
            print(f"[LIGADÃO] Resposta: {result.keys()}")
            
            parts = result.get("parts", [])
            for part in parts:
                if part.get("type") == "text":
                    texto = part.get("text", "")
                    if texto.strip():
                        await self._send_or_edit(texto)
                elif part.get("type") == "tool":
                    tool = part.get("tool", "?")
                    await self._send_or_edit(f"🔧 *Tool:* `{tool}`")
            
            info = result.get("info", {})
            error = info.get("error", "")
            if error:
                await self._send_or_edit(f"❌ *Erro:* {error}")
            else:
                await self._send_or_edit("✅ *Concluído*")
                
        except Exception as e:
            print(f"[LIGADÃO] Erro: {e}")
            await self._send_or_edit(f"❌ Erro: {e}")
    
    async def _send_or_edit(self, text: str):
        if self.last_message_id:
            try:
                await edit_message(self.chat_id, self.last_message_id, text)
                return
            except Exception:
                pass
        msg = await send_message(self.chat_id, text)
        self.last_message_id = msg.get("message_id") if isinstance(msg, dict) else None
    
    async def close(self):
        if self.client:
            await self.client.aclose()
        print(f"[LIGADÃO] Sessão encerrada para chat {self.chat_id}")


async def _entrar_ligado(chat_id: int):
    if chat_id in _ligado_sessions:
        await send_message(chat_id, "⚡ Já no modo Ligadão. Mande qualquer texto para o OpenCode.")
        return
    
    session = LigadoSession(chat_id)
    try:
        await session.start()
        _ligado_sessions[chat_id] = session
        await send_message(chat_id, "⚡ **Modo Ligadão ativo**\n\nAgora mande qualquer texto — será enviado direto pro OpenCode.\nUse /soninho para sair.")
        print(f"[LIGADÃO] Chat {chat_id} entrou no modo Ligadão")
    except Exception as e:
        await send_message(chat_id, f"❌ Erro ao conectar OpenCode: {e}")


async def _sair_ligado(chat_id: int):
    session = _ligado_sessions.pop(chat_id, None)
    if session:
        await session.close()
        await send_message(chat_id, "😴 Sessão Ligadão encerrada.")
    else:
        await send_message(chat_id, "Não há sessão Ligadão ativa.")


async def _ligado_enviar_prompt(chat_id: int, text: str):
    session = _ligado_sessions[chat_id]
    await session.send_prompt(text)
    await send_message(chat_id, "📤 Enviado pro OpenCode... aguarde.")


async def _processar_confirmacao_qualificada(user_id: int, chat_id: int, text: str):
    pend = _aguardando_qualificacao.pop(chat_id, None)
    if not pend:
        return

    descricao_norm = pend.get("descricao_norm", "")
    texto_norm = _normalizar(text)

    if descricao_norm and descricao_norm in texto_norm:
        result = await call_daemon_aprovar(pend["thread_id"], {
            "resposta": text,
            "aprovado": True,
            "usuario": user_id,
        })
        status = result.get("status", "desconhecido")
        acao_status = result.get("acao_status", "")
        msg_final = result.get("mensagem_final", "")
        linha = f"✅ Aprovado! Status: {status}"
        if acao_status:
            linha += f" | ação: {acao_status}"
        await send_message(chat_id, linha)
        if msg_final:
            await send_message(chat_id, f"📋 {msg_final}")
    else:
        result = await call_daemon_aprovar(pend["thread_id"], {
            "resposta": text,
            "aprovado": False,
            "usuario": user_id,
        })
        await send_message(chat_id,
            "❌ Confirmação inválida — a ação foi REJEITADA e NÃO será executada.\n"
            "O resumo digitado não corresponde à ação solicitada.")


async def poll():
    global _offset
    print(f"[TELEGRAM BOT] Iniciando polling (daemon: {DAEMON_URL}, opencode: {OPENCODE_URL})")
    print(f"[TELEGRAM BOT] Usuarios autorizados: {ALLOWED_USERS or 'todos'}")

    async with aiohttp.ClientSession() as session:
        # Remove webhook antigo (Telegram nao permite polling + webhook)
        async with session.post(f"{API_BASE}/deleteWebhook") as resp:
            data = await resp.json()
            print(f"[TELEGRAM BOT] deleteWebhook: {data}")

        while True:
            try:
                params = {"offset": _offset, "timeout": 30}
                async with session.get(f"{API_BASE}/getUpdates", params=params, timeout=aiohttp.ClientTimeout(total=35)) as resp:
                    data = await resp.json()

                if not data.get("ok"):
                    print(f"[TELEGRAM BOT] Erro: {data}")
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    _offset = update["update_id"] + 1

                    if "callback_query" in update:
                        await handle_callback_query(update["callback_query"])
                    elif "message" in update:
                        await handle_message(update["message"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[TELEGRAM BOT] Erro no polling: {e}")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(poll())