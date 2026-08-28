from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin

import httpx


@dataclass
class ExecutionResult:
    success: bool
    output: str = ""
    error: str = ""
    messages: list[dict[str, Any]] = None
    run_id: str = ""
    session_id: str = ""
    completed_at: datetime = None
    
    def __post_init__(self):
        if self.messages is None:
            self.messages = []
        if self.completed_at is None:
            self.completed_at = datetime.now()


@dataclass
class CrushConfig:
    server_url: str = "http://localhost:9876"
    workspace_path: str = "/workspace"
    connect_timeout: float = 30.0
    request_timeout: float = 300.0
    sse_timeout: float = 600.0


class CrushClient:
    """
    Cliente assíncrono para Crush Server (HTTP REST + SSE).
    
    Substitui CAO/OpenCode — roda nativamente no Windows/Linux/macOS.
    Não requer tmux, fcntl ou automação de TUI.
    """
    
    def __init__(self, config: CrushConfig | None = None):
        self.config = config or CrushConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._sse_client: Optional[httpx.AsyncClient] = None
        self.workspace_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._sse_task: Optional[asyncio.Task] = None
        self._connected = False
        self._pending_permissions: dict[str, asyncio.Future] = {}
        self._pending_questions: dict[str, asyncio.Future] = {}
        self._run_complete_futures: dict[str, asyncio.Future] = {}
    
    async def __aenter__(self) -> "CrushClient":
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def connect(self) -> "CrushClient":
        """Conecta ao Crush Server, cria/obtém workspace e inicia SSE stream."""
        self._client = httpx.AsyncClient(
            base_url=self.config.server_url,
            timeout=httpx.Timeout(self.config.connect_timeout),
        )
        
        # Verificar saúde do servidor
        await self._health_check()
        
        # Criar/obter workspace
        self.workspace_id = await self._ensure_workspace()
        
        # Iniciar SSE stream para eventos em tempo real
        self._sse_client = httpx.AsyncClient(
            base_url=self.config.server_url,
            timeout=httpx.Timeout(None),  # Sem timeout para SSE
        )
        self._sse_task = asyncio.create_task(self._listen_sse())
        
        # Aguardar conexão SSE estabelecida
        await asyncio.sleep(0.5)
        self._connected = True
        return self
    
    async def _health_check(self) -> None:
        resp = await self._client.get("/v1/health")
        resp.raise_for_status()
    
    async def _ensure_workspace(self) -> str:
        """Cria ou obtém workspace existente pelo path."""
        # Tentar listar workspaces existentes
        resp = await self._client.get("/v1/workspaces")
        resp.raise_for_status()
        workspaces = resp.json()
        
        for ws in workspaces:
            if ws.get("path") == self.config.workspace_path:
                return ws["id"]
        
        # Criar novo workspace
        resp = await self._client.post(
            "/v1/workspaces",
            json={"path": self.config.workspace_path},
        )
        resp.raise_for_status()
        workspace = resp.json()
        return workspace["id"]
    
    async def _ensure_session(self, title: str | None = None) -> str:
        """Cria ou reusa sessão no workspace."""
        if self.session_id:
            # Verificar se sessão ainda existe
            try:
                resp = await self._client.get(
                    f"/v1/workspaces/{self.workspace_id}/sessions/{self.session_id}"
                )
                if resp.status_code == 200:
                    return self.session_id
            except Exception:
                pass
        
        # Criar nova sessão
        resp = await self._client.post(
            f"/v1/workspaces/{self.workspace_id}/sessions",
            json={"title": title or f"harmonia-{datetime.now().strftime('%Y%m%d-%H%M%S')}"},
        )
        resp.raise_for_status()
        session = resp.json()
        self.session_id = session["id"]
        return self.session_id
    
    async def _listen_sse(self) -> None:
        """Escuta eventos SSE do workspace em background."""
        url = f"/v1/workspaces/{self.workspace_id}/events"
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
            pass
        except Exception as e:
            # Log erro mas não derruba o cliente
            print(f"[CrushClient] SSE error: {e}")
    
    async def _handle_event(self, event: dict[str, Any]) -> None:
        """Processa evento SSE e resolve futures pendentes."""
        event_type = event.get("type", "")
        payload = event.get("payload", {})
        
        # Enfileirar para consumo geral
        await self._event_queue.put({"type": event_type, "payload": payload})
        
        # Resolver futures específicas
        if event_type == "permission_request":
            perm_id = payload.get("id")
            if perm_id in self._pending_permissions:
                self._pending_permissions[perm_id].set_result(payload)
        
        elif event_type == "question_request":
            batch_id = payload.get("id")
            if batch_id in self._pending_questions:
                self._pending_questions[batch_id].set_result(payload)
        
        elif event_type == "run_complete":
            run_id = payload.get("run_id", "")
            session_id = payload.get("session_id", "")
            key = run_id or session_id
            if key in self._run_complete_futures:
                self._run_complete_futures[key].set_result(payload)
    
    async def execute(
        self,
        prompt: str,
        run_id: str | None = None,
        session_title: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionResult:
        """
        Executa um prompt no Crush e aguarda conclusão.
        
        Args:
            prompt: Instrução para o agente
            run_id: ID único para correlacionar RunComplete (usa action_id do Harmonia)
            session_title: Título opcional para nova sessão
            timeout: Timeout customizado (padrão: config.sse_timeout)
        
        Returns:
            ExecutionResult com sucesso, output, mensagens, etc.
        """
        if not self._connected:
            raise RuntimeError("CrushClient não conectado. Use 'async with' ou chame connect().")
        
        run_id = run_id or str(uuid.uuid4())
        timeout = timeout or self.config.sse_timeout
        
        # Garantir sessão
        session_id = await self._ensure_session(session_title)
        
        # Criar future para RunComplete
        complete_future = asyncio.get_event_loop().create_future()
        self._run_complete_futures[run_id] = complete_future
        
        try:
            # Enviar prompt
            await self._send_message(session_id, prompt, run_id)
            
            # Aguardar conclusão com timeout
            try:
                result = await asyncio.wait_for(complete_future, timeout=timeout)
            except asyncio.TimeoutError:
                return ExecutionResult(
                    success=False,
                    error=f"Timeout após {timeout}s aguardando conclusão",
                    run_id=run_id,
                    session_id=session_id,
                )
            
            # Buscar mensagens da sessão para retorno completo
            messages = await self._get_session_messages(session_id)
            
            # Determinar sucesso
            error = result.get("error", "")
            cancelled = result.get("cancelled", False)
            success = not error and not cancelled
            
            return ExecutionResult(
                success=success,
                output=result.get("text", ""),
                error=error,
                messages=messages,
                run_id=run_id,
                session_id=session_id,
            )
        
        finally:
            self._run_complete_futures.pop(run_id, None)
    
    async def _send_message(self, session_id: str, prompt: str, run_id: str) -> None:
        resp = await self._client.post(
            f"/v1/workspaces/{self.workspace_id}/agent",
            json={
                "session_id": session_id,
                "prompt": prompt,
                "run_id": run_id,
            },
        )
        resp.raise_for_status()
        # 202 Accepted = mensagem enfileirada, execução assíncrona
    
    async def _get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        resp = await self._client.get(
            f"/v1/workspaces/{self.workspace_id}/sessions/{session_id}/messages"
        )
        resp.raise_for_status()
        return resp.json()
    
    async def grant_permission(self, tool_call_id: str, allow: bool, for_session: bool = False) -> bool:
        """Concede/nega permissão para uma tool call."""
        # Primeiro, obter o permission request ID via eventos ou assumir tool_call_id
        # A API espera o permission object completo
        action = "allow_session" if (allow and for_session) else ("allow" if allow else "deny")
        
        # Precisamos do permission request completo - vamos buscar via eventos
        # Por simplicidade, assumimos que o tool_call_id pode ser usado
        # Na prática, o Harmonia deve capturar o PermissionRequest do SSE
        resp = await self._client.post(
            f"/v1/workspaces/{self.workspace_id}/permissions/grant",
            json={
                "permission": {
                    "tool_call_id": tool_call_id,
                },
                "action": action,
            },
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("resolved", False)
    
    async def answer_question(self, batch_id: str, responses: list[dict[str, Any]]) -> bool:
        """Responde a uma batch question."""
        resp = await self._client.post(
            f"/v1/workspaces/{self.workspace_id}/questions/answer",
            json={
                "batch_request_id": batch_id,
                "responses": responses,
            },
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("resolved", False)
    
    async def cancel_session(self, session_id: str | None = None) -> None:
        """Cancela execução em andamento."""
        sid = session_id or self.session_id
        if sid:
            resp = await self._client.post(
                f"/v1/workspaces/{self.workspace_id}/agent/sessions/{sid}/cancel"
            )
            resp.raise_for_status()
    
    async def run_shell(self, command: str, session_id: str | None = None) -> dict[str, Any]:
        """Executa comando shell direto no workspace."""
        sid = session_id or self.session_id
        if not sid:
            raise ValueError("Nenhuma sessão ativa")
        
        resp = await self._client.post(
            f"/v1/workspaces/{self.workspace_id}/agent/sessions/{sid}/shell",
            json={"command": command},
        )
        resp.raise_for_status()
        return resp.json()
    
    async def wait_for_permission(self, tool_call_id: str, timeout: float = 60.0) -> dict[str, Any]:
        """Aguarda PermissionRequest para um tool_call_id específico."""
        future = asyncio.get_event_loop().create_future()
        self._pending_permissions[tool_call_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_permissions.pop(tool_call_id, None)
    
    async def wait_for_question(self, batch_id: str, timeout: float = 60.0) -> dict[str, Any]:
        """Aguarda QuestionRequest para um batch_id específico."""
        future = asyncio.get_event_loop().create_future()
        self._pending_questions[batch_id] = future
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending_questions.pop(batch_id, None)
    
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


async def criar_cliente_crush(
    server_url: str = "http://localhost:9876",
    workspace_path: str = "/workspace",
) -> CrushClient:
    """Factory para criar e conectar cliente Crush."""
    config = CrushConfig(server_url=server_url, workspace_path=workspace_path)
    client = CrushClient(config)
    await client.connect()
    return client