from __future__ import annotations

import httpx
import asyncio
import subprocess
import time
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class CAOConfig:
    host: str = "localhost"
    port: int = 8080
    base_url: str = ""
    
    def __post_init__(self):
        if not self.base_url:
            self.base_url = f"http://{self.host}:{self.port}"


class CAOClient:
    """
    Cliente para cli-agent-orchestrator (CAO).
    
    Requer:
    - pip install cli-agent-orchestrator
    - tmux instalado no sistema
    - cao-server rodando (investigar comando exato no CODEBASE.md do repo AWS)
    - Provider: opencode_cli (NÃO 'opencode')
    - Flag --yolo: NUNCA usar
    """
    
    def __init__(self, config: CAOConfig | None = None):
        self.config = config or CAOConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._server_process: Optional[subprocess.Popen] = None
    
    async def __aenter__(self):
        await self._garantir_server_rodando()
        self._client = httpx.AsyncClient(base_url=self.config.base_url, timeout=300.0)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    async def _garantir_server_rodando(self):
        """Verifica se cao-server está rodando, sobe se necessário."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.config.base_url}/health", timeout=5.0)
                if resp.status_code == 200:
                    return
        except Exception:
            pass
        
        self._server_process = subprocess.Popen(
            ["cao", "server"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        for _ in range(30):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{self.config.base_url}/health", timeout=2.0)
                    if resp.status_code == 200:
                        return
            except Exception:
                continue
        
        raise RuntimeError("cao-server não subiu após 30s. Verifique 'cao --help' e CODEBASE.md do awslabs/cli-agent-orchestrator")
    
    async def executar(
        self,
        prompt: str,
        provider: str = "opencode_cli",
        agents: list[str] = None,
        session_id: str = None,
    ) -> dict[str, Any]:
        """
        Executa uma tarefa via CAO.
        
        Equivalente a: cao launch --agents developer --provider opencode_cli
        """
        if not self._client:
            raise RuntimeError("CAOClient não inicializado. Use async with.")
        
        payload = {
            "prompt": prompt,
            "provider": provider,
            "agents": agents or ["developer"],
        }
        
        if session_id:
            payload["session_id"] = session_id
        
        resp = await self._client.post("/api/v1/execute", json=payload)
        resp.raise_for_status()
        
        return resp.json()
    
    async def listar_sessoes(self) -> list[dict]:
        if not self._client:
            raise RuntimeError("CAOClient não inicializado")
        
        resp = await self._client.get("/api/v1/sessions")
        resp.raise_for_status()
        return resp.json()
    
    async def obter_sessao(self, session_id: str) -> dict:
        if not self._client:
            raise RuntimeError("CAOClient não inicializado")
        
        resp = await self._client.get(f"/api/v1/sessions/{session_id}")
        resp.raise_for_status()
        return resp.json()


async def executar_via_opencode(
    prompt: str,
    provider: str = "opencode_cli",
    agents: list[str] = None,
) -> dict[str, Any]:
    """
    Função de conveniência para execução única.
    
    ATENÇÃO: Esta é a implementação real que substitui o NotImplementedError.
    Requer cao-server rodando e tmux instalado.
    """
    async with CAOClient() as client:
        return await client.executar(prompt, provider, agents)