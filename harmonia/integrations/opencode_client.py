from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urljoin

import httpx


@dataclass
class ExecutionResult:
    success: bool
    output: str = ""
    error: str = ""
    messages: list[dict[str, Any]] = None
    session_id: str = ""
    completed_at: datetime = None
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []
        if self.completed_at is None:
            self.completed_at = datetime.now()


@dataclass
class OpenCodeConfig:
    server_url: str = "http://localhost:4096"
    username: str = "opencode"
    password: str = ""
    connect_timeout: float = 30.0
    request_timeout: float = 300.0
    sse_timeout: float = 600.0


class OpenCodeClient:
    """
    Cliente assíncrono para OpenCode Server (HTTP REST + SSE).
    
    Usa a API oficial do `opencode serve`:
    - POST /session/:id/message - envia prompt e aguarda resposta
    - GET /event (SSE) - stream de eventos em tempo real
    - POST /session/:id/permissions/:permissionID - responde permissões
    - POST /session/:id/abort - cancela execução
    """
    
    def __init__(self, config: OpenCodeConfig | None = None):
        self.config = config or OpenCodeConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._sse_client: Optional[httpx.AsyncClient] = None
        self.session_id: Optional[str] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._sse_task: Optional[asyncio.Task] = None
        self._connected = False
        self._pending_permissions: dict[str, asyncio.Future] = {}
        self._run_complete_futures: dict[str, asyncio.Future] = {}
        self._message_futures: dict[str, asyncio.Future] = {}
    
    async def __aenter__(self) -> "OpenCodeClient":
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    def _get_auth(self) -> tuple[str, str] | None:
        if self.config.password:
            return (self.config.username, self.config.password)
        return None
    
    async def connect(self) -> "OpenCodeClient":
        """Conecta ao OpenCode Server, verifica saúde e inicia SSE stream."""
        self._client = httpx.AsyncClient(
            base_url=self.config.server_url,
            timeout=httpx.Timeout(self.config.connect_timeout),
            auth=self._get_auth(),
        )
        
        # Verificar saúde do servidor
        await self._health_check()
        
        # Iniciar SSE stream para eventos globais
        self._sse_client = httpx.AsyncClient(
            base_url=self.config.server_url,
            timeout=httpx.Timeout(None),  # Sem timeout para SSE
            auth=self._get_auth(),
        )
        self._sse_task = asyncio.create_task(self._listen_sse())
        
        # Aguardar conexão SSE estabelecida
        await asyncio.sleep(1)
        self._connected = True
        return self
    
    async def _health_check(self) -> None:
        resp = await self._client.get("/global/health")
        resp.raise_for_status()
        data = resp.json()
        print(f"[OpenCodeClient] Server healthy: {data}")
    
    async def _ensure_session(self, title: str | None = None) -> str:
        """Cria ou reusa sessão no OpenCode."""
        if self.session_id:
            # Verificar se sessão ainda existe
            try:
                resp = await self._client.get(f"/session/{self.session_id}")
                if resp.status_code == 200:
                    return self.session_id
            except Exception:
                pass
        
        # Criar nova sessão
        resp = await self._client.post(
            "/session",
            json={"title": title or f"harmonia-{datetime.now().strftime('%Y%m%d-%H%M%S')}"},
        )
        resp.raise_for_status()
        session = resp.json()
        self.session_id = session["id"]
        print(f"[OpenCodeClient] Created session: {self.session_id}")
        return self.session_id
    
    async def _listen_sse(self) -> None:
        """Escuta eventos SSE do OpenCode em background com reconexão automática."""
        url = "/event"
        while True:
            try:
                async with self._sse_client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                event = json.loads(line[6:])
                                await self._handle_event(event)
                            except json.JSONDecodeError:
                                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[OpenCodeClient] SSE error: {e} — reconectando em 2s...")
                await asyncio.sleep(2)
                continue
    
    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Processa evento SSE e resolve futures pendentes."""
        event_type = event.get("type", "")
        payload = event.get("payload", event)  # OpenCode pode mandar payload direto
        
        # Enfileirar para consumo geral
        await self._event_queue.put({"type": event_type, "payload": payload})
        
        # Resolver futures específicas
        if event_type == "session.permission":
            perm_id = payload.get("id") or payload.get("permissionID")
            if perm_id and perm_id in self._pending_permissions:
                self._pending_permissions[perm_id].set_result(payload)
        
        elif event_type in ("session.message", "message"):
            # Resposta de mensagem assíncrona ou streaming
            msg_id = payload.get("id") or payload.get("messageID")
            if msg_id and msg_id in self._message_futures:
                self._message_futures[msg_id].set_result(payload)
        
        elif event_type in ("session.complete", "run_complete", "complete"):
            session_id = payload.get("sessionID") or payload.get("session_id")
            if session_id and session_id in self._run_complete_futures:
                self._run_complete_futures[session_id].set_result(payload)
    
    async def execute(
        self,
        prompt: str,
        session_title: str | None = None,
        timeout: float | None = None,
        model: str | None = None,
        agent: str | None = None,
    ) -> ExecutionResult:
        """
        Executa um prompt no OpenCode e aguarda conclusão.
        
        Usa POST /session/:id/message que AGUARDA a resposta completa.
        """
        if not self._connected:
            raise RuntimeError("OpenCodeClient não conectado. Use 'async with' ou chame connect().")
        
        timeout = timeout or self.config.sse_timeout
        
        # Garantir sessão
        session_id = await self._ensure_session(session_title)
        
        # Formato de modelo esperado pelo OpenCode
        model_payload = None
        if model:
            # Se passou string simples, converter para objeto
            if isinstance(model, str):
                if model.startswith("nvidia/"):
                    # nvidia/nemotron-3-ultra -> nemotron-3-ultra-free via opencode provider
                    model_payload = {
                        "modelID": "nemotron-3-ultra-free",
                        "providerID": "opencode",
                        "variant": "default"
                    }
                else:
                    model_payload = {"modelID": model, "providerID": "opencode", "variant": "default"}
            else:
                model_payload = model
        else:
            # Default para nemotron-3-ultra-free
            model_payload = {
                "modelID": "nemotron-3-ultra-free",
                "providerID": "opencode",
                "variant": "default"
            }
        
        # Criar future para resposta
        # OpenCode /message retorna a resposta completa diretamente
        try:
            resp = await self._client.post(
                f"/session/{session_id}/message",
                json={
                    "parts": [{"type": "text", "text": prompt}],
                    "model": model_payload,
                    "agent": agent,
                },
                timeout=httpx.Timeout(timeout),
            )
            resp.raise_for_status()
            result = resp.json()
            
            # Extrair resultado
            info = result.get("info", {})
            parts = result.get("parts", [])
            
            # Montar output textual
            output_parts = []
            for part in parts:
                if part.get("type") == "text":
                    output_parts.append(part.get("text", ""))
                elif part.get("type") == "tool":
                    output_parts.append(f"[Tool: {part.get('tool', 'unknown')}]")
            
            output = "\n".join(output_parts)
            
            # Verificar erro
            error = info.get("error", "") or ""
            success = not error
            
            # Buscar mensagens da sessão para histórico
            messages = await self._get_session_messages(session_id)
            
            return ExecutionResult(
                success=success,
                output=output,
                error=error,
                messages=messages,
                session_id=session_id,
            )
        
        except httpx.TimeoutException:
            return ExecutionResult(
                success=False,
                error=f"Timeout após {timeout}s aguardando resposta",
                session_id=session_id,
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                session_id=session_id,
            )
    
    async def execute_async(
        self,
        prompt: str,
        session_title: str | None = None,
        model: str | None = None,
        agent: str | None = None,
    ) -> str:
        """
        Envia prompt de forma assíncrona (não aguarda).
        Retorna message_id para correlacionar com eventos SSE.
        """
        session_id = await self._ensure_session(session_title)
        
        message_id = str(uuid.uuid4())
        
        # Criar future para resposta via SSE
        future = asyncio.get_event_loop().create_future()
        self._message_futures[message_id] = future
        
        # Formato de modelo esperado pelo OpenCode
        model_payload = None
        if model:
            if isinstance(model, str):
                if model.startswith("nvidia/"):
                    model_payload = {
                        "modelID": "nemotron-3-ultra-free",
                        "providerID": "opencode",
                        "variant": "default"
                    }
                else:
                    model_payload = {"modelID": model, "providerID": "opencode", "variant": "default"}
            else:
                model_payload = model
        else:
            model_payload = {
                "modelID": "nemotron-3-ultra-free",
                "providerID": "opencode",
                "variant": "default"
            }
        
        resp = await self._client.post(
            f"/session/{session_id}/prompt_async",
            json={
                "messageID": message_id,
                "parts": [{"type": "text", "text": prompt}],
                "model": model_payload,
                "agent": agent,
            },
        )
        resp.raise_for_status()
        
        return message_id
    
    async def wait_for_message(self, message_id: str, timeout: float = 300.0) -> ExecutionResult:
        """Aguarda conclusão de mensagem enviada via execute_async."""
        future = self._message_futures.get(message_id)
        if not future:
            raise ValueError(f"Message ID {message_id} não encontrado")
        
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            messages = await self._get_session_messages(self.session_id or "")
            
            # Extrair output
            parts = result.get("parts", [])
            output_parts = []
            for part in parts:
                if part.get("type") == "text":
                    output_parts.append(part.get("text", ""))
            
            error = result.get("info", {}).get("error", "") or ""
            
            return ExecutionResult(
                success=not error,
                output="\n".join(output_parts),
                error=error,
                messages=messages,
                session_id=self.session_id or "",
            )
        finally:
            self._message_futures.pop(message_id, None)
    
    async def _get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        resp = await self._client.get(f"/session/{session_id}/message?limit=50")
        resp.raise_for_status()
        return resp.json()
    
    async def grant_permission(self, permission_id: str, allow: bool, remember: bool = False) -> bool:
        """Responde a um pedido de permissão do OpenCode."""
        resp = await self._client.post(
            f"/session/{self.session_id}/permissions/{permission_id}",
            json={
                "response": "allow" if allow else "deny",
                "remember": remember,
            },
        )
        resp.raise_for_status()
        return True
    
    async def abort_session(self, session_id: str | None = None) -> bool:
        """Cancela execução em andamento."""
        sid = session_id or self.session_id
        if sid:
            resp = await self._client.post(f"/session/{sid}/abort")
            resp.raise_for_status()
            return True
        return False
    
    async def run_shell(self, command: str, agent: str = "coder", model: str | None = None) -> dict[str, Any]:
        """Executa comando shell direto no workspace."""
        sid = self.session_id
        if not sid:
            raise ValueError("Nenhuma sessão ativa")
        
        resp = await self._client.post(
            f"/session/{sid}/shell",
            json={"command": command, "agent": agent, "model": model},
        )
        resp.raise_for_status()
        return resp.json()
    
    async def wait_for_permission(self, permission_id: str, timeout: float = 60.0) -> dict[str, Any]:
        """Aguarda PermissionRequest para um permission_id específico."""
        future = asyncio.get_event_loop().create_future()
        self._pending_permissions[permission_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_permissions.pop(permission_id, None)
    
    async def get_events(self, max_events: int = 10) -> list[dict[str, Any]]:
        """Consome eventos da queue (não-bloqueante)."""
        events = []
        for _ in range(max_events):
            try:
                events.append(self._event_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events
    
    async def close(self) -> None:
        """Fecha conexões e limpa recursos."""
        self._connected = False
        
        if self._sse_task:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
        
        if self._sse_client:
            await self._sse_client.aclose()
        
        if self._client:
            await self._client.aclose()


async def criar_cliente_opencode(
    server_url: str = "http://localhost:4096",
    password: str = "",
) -> OpenCodeClient:
    """Factory para criar e conectar cliente OpenCode."""
    config = OpenCodeConfig(server_url=server_url, password=password)
    client = OpenCodeClient(config)
    await client.connect()
    return client