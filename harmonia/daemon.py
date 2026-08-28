#!/usr/bin/env python3
"""
Daemon Harmonia - Processo contínuo que:
1. Escuta webhooks de aprovação (Telegram/WhatsApp)
2. Aceita submissão de novos planos via HTTP
3. Gerencia execução contínua de múltiplos planos (threads)
4. Persiste estado no SQLite checkpoint
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from harmonia.graph.build import criar_estado_inicial, compilar_com_checkpoint, fechar_checkpointer
from harmonia.graph.state import HarmoniaState
from langgraph.types import Command


class PlanoSubmissao(BaseModel):
    plano: dict
    dial: str = "soninho"
    thread_id: Optional[str] = None


class AprovacaoPayload(BaseModel):
    thread_id: str
    resposta: dict
    acao_id: Optional[str] = None


class HarmoniaDaemon:
    def __init__(self, host: str = "0.0.0.0", port: int = 8081):
        self.host = host
        self.port = port
        self.graph = None
        self.conn = None
        self._running = False
        self._tasks: Dict[str, asyncio.Task] = {}
        self._keepalive_task: Optional[asyncio.Task] = None
        self.app = self._criar_app()
    
    def _criar_app(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await self.iniciar()
            yield
            await self.parar()
        
        app = FastAPI(title="Harmonia Daemon", lifespan=lifespan)
        
        @app.post("/plano")
        async def submeter_plano(submissao: PlanoSubmissao):
            return await self._executar_plano(submissao)
        
        @app.post("/aprovar")
        async def aprovar_acao(aprovacao: AprovacaoPayload):
            return await self._processar_aprovacao(aprovacao)
        
        @app.get("/status/{thread_id}")
        async def status_plano(thread_id: str):
            return await self._obter_status(thread_id)
        
        @app.get("/health")
        async def health():
            return {"status": "ok", "daemon": "running"}
        
        @app.post("/auditoria")
        async def trigger_auditoria(request: Request):
            """Dispara o auditor para escanear o repo e gerar/executar plano."""
            body = await request.json()
            dial = body.get("dial", "soninho")
            thread_id = body.get("thread_id", f"auditoria-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            
            print(f"[DAEMON] Auditor disparado: thread_id={thread_id}, dial={dial}")
            
            # Estado inicial vazio - o auditor vai gerar o plano
            state = criar_estado_inicial(
                plano_id=thread_id,
                fundamentos=[],
                etapas=[],
                dial=dial,
            )
            
            config = {"configurable": {"thread_id": thread_id}}
            
            try:
                resultado = await self.graph.ainvoke(state, config=config)
                
                fila = resultado.get("fila_aprovacao", [])
                execs = resultado.get("acoes_executadas", [])
                pendentes = resultado.get("acoes_pendentes", [])
                
                response = {
                    "thread_id": thread_id,
                    "status": "pausado" if fila else "concluido",
                    "acoes_executadas": len(execs),
                    "acoes_pendentes": len(pendentes),
                    "fila_aprovacao": len(fila),
                    "mensagem_final": resultado.get("mensagem_final", ""),
                }
                
                if fila:
                    solicitacao = fila[-1]
                    acao_descricao = ""
                    for acao in pendentes:
                        if acao.get("id") == solicitacao.get("acao_id"):
                            acao_descricao = acao.get("descricao", "")
                            break
                    response["solicitacao"] = {
                        "solicitacao_id": solicitacao.get("id"),
                        "acao_id": solicitacao.get("acao_id"),
                        "mensagem": solicitacao.get("mensagem"),
                        "confirmacao_qualificada": solicitacao.get("confirmacao_qualificada", False),
                        "acao_descricao": acao_descricao,
                    }
                
                return response
                
            except Exception as e:
                return JSONResponse(
                    status_code=500,
                    content={"erro": str(e), "thread_id": thread_id}
                )
        
        return app
    
    async def iniciar(self):
        print("[DAEMON] Iniciando Harmonia Daemon...")
        self.graph, self.conn = await compilar_com_checkpoint()
        self._running = True
        
        # Iniciar keep-alive interno (evita hibernação do Codespace)
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        print("[KEEPALIVE] Task iniciada (intervalo: 20 min)")
        
        print(f"[DAEMON] Rodando em http://{self.host}:{self.port}")
        print("[DAEMON] Endpoints:")
        print("  POST /plano      - Submeter novo plano")
        print("  POST /auditoria  - Disparar auditoria automática")
        print("  POST /aprovar    - Enviar aprovação para thread pausada")
        print("  GET  /status/{thread_id} - Ver status de um plano")
        print("  GET  /health     - Health check")
    
    async def _keepalive_loop(self):
        """Task em background que roda a cada 20 min para evitar hibernação do Codespace."""
        keepalive_file = Path(__file__).parent.parent / ".harmonia_keepalive"
        while self._running:
            await asyncio.sleep(1200)  # 20 min = 1200s (Codespace timeout = 30 min)
            if self._running:
                try:
                    keepalive_file.write_text(datetime.now().isoformat())
                    print(f"[KEEPALIVE] Atividade registrada: {datetime.now().isoformat()}")
                except Exception as e:
                    print(f"[KEEPALIVE] Erro: {e}")
    
    async def parar(self):
        print("[DAEMON] Parando...")
        self._running = False
        
        # Cancelar keep-alive
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        
        # Cancelar tasks pendentes
        for task in self._tasks.values():
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        
        if self.conn:
            await self.conn.close()
        
        await fechar_checkpointer()
        print("[DAEMON] Parado.")
    
    async def _executar_plano(self, submissao: PlanoSubmissao) -> dict:
        plano = submissao.plano
        dial = submissao.dial
        thread_id = submissao.thread_id or plano.get("plano_id", "sem-id")
        
        print(f"[DAEMON] Novo plano: {thread_id} (dial: {dial})")
        
        state = criar_estado_inicial(
            plano_id=thread_id,
            fundamentos=plano.get("fundamentos", []),
            etapas=plano.get("etapas", []),
            dial=dial,
        )
        
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            resultado = await self.graph.ainvoke(state, config=config)
            
            fila = resultado.get("fila_aprovacao", [])
            execs = resultado.get("acoes_executadas", [])
            pendentes = resultado.get("acoes_pendentes", [])
            
            response = {
                "thread_id": thread_id,
                "status": "pausado" if fila else "concluido",
                "acoes_executadas": len(execs),
                "acoes_pendentes": len(pendentes),
                "fila_aprovacao": len(fila),
            }
            
            if fila:
                solicitacao = fila[-1]
                response["aguardando_aprovacao"] = {
                    "solicitacao_id": solicitacao.get("id"),
                    "acao_id": solicitacao.get("acao_id"),
                    "mensagem": solicitacao.get("mensagem"),
                    "confirmacao_qualificada": solicitacao.get("confirmacao_qualificada", False),
                }
            
            return response
            
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"erro": str(e), "thread_id": thread_id}
            )
    
    async def _processar_aprovacao(self, aprovacao: AprovacaoPayload) -> dict:
        thread_id = aprovacao.thread_id
        resposta = aprovacao.resposta
        
        print(f"[DAEMON] Aprovação recebida para thread: {thread_id}")
        
        if not self.graph:
            raise HTTPException(status_code=503, detail="Daemon não inicializado")
        
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            resultado = await self.graph.ainvoke(
                Command(resume=resposta),
                config=config
            )
            
            fila = resultado.get("fila_aprovacao", [])
            execs = resultado.get("acoes_executadas", [])
            pendentes = resultado.get("acoes_pendentes", [])
            
            acao_status = ""
            if pendentes:
                acao_status = pendentes[0].get("status", "")
            elif execs:
                acao_status = execs[-1].get("status", "concluida")
            
            response = {
                "thread_id": thread_id,
                "status": "pausado" if fila else "concluido",
                "acoes_executadas": len(execs),
                "acoes_pendentes": len(pendentes),
                "acao_status": acao_status,
                "mensagem_final": resultado.get("mensagem_final", ""),
            }
            
            if fila:
                solicitacao = fila[-1]
                response["aguardando_aprovacao"] = {
                    "solicitacao_id": solicitacao.get("id"),
                    "acao_id": solicitacao.get("acao_id"),
                    "mensagem": solicitacao.get("mensagem"),
                }
            
            return response
            
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"erro": str(e), "thread_id": thread_id}
            )
    
    async def _obter_status(self, thread_id: str) -> dict:
        if not self.graph:
            raise HTTPException(status_code=503, detail="Daemon não inicializado")
        
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            state_snapshot = await self.graph.aget_state(config)
            
            if not state_snapshot.values:
                raise HTTPException(status_code=404, detail="Thread não encontrada")
            
            values = state_snapshot.values
            fila = values.get("fila_aprovacao", [])
            execs = values.get("acoes_executadas", [])
            pendentes = values.get("acoes_pendentes", [])
            
            pendentes_ativos = [
                a for a in pendentes
                if a.get("status") in ("pendente", "aguardando_aprovacao", "executando")
            ]
            
            response = {
                "thread_id": thread_id,
                "status": "pausado" if fila else ("concluido" if not pendentes_ativos else "executando"),
                "acoes_executadas": len(execs),
                "acoes_pendentes": len(pendentes),
                "proximo_no": state_snapshot.next,
                "aguardando_aprovacao": bool(fila),
                "mensagem_final": values.get("mensagem_final", ""),
            }
            
            if fila:
                solicitacao = fila[-1]
                acao_descricao = ""
                for acao in pendentes:
                    if acao.get("id") == solicitacao.get("acao_id"):
                        acao_descricao = acao.get("descricao", "")
                        break
                response["solicitacao"] = {
                    "solicitacao_id": solicitacao.get("id"),
                    "acao_id": solicitacao.get("acao_id"),
                    "mensagem": solicitacao.get("mensagem"),
                    "confirmacao_qualificada": solicitacao.get("confirmacao_qualificada", False),
                    "acao_descricao": acao_descricao,
                }
            
            return response
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    def run(self):
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info", lifespan="on")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Harmonia Daemon")
    parser.add_argument("--host", default="0.0.0.0", help="Host para bind")
    parser.add_argument("--port", type=int, default=8081, help="Porta para bind")
    args = parser.parse_args()
    
    daemon = HarmoniaDaemon(host=args.host, port=args.port)
    
    # Iniciar daemon (compila grafo, abre conexão DB)
    await daemon.iniciar()
    
    # Rodar servidor uvicorn (bloqueia até shutdown)
    config = uvicorn.Config(daemon.app, host=args.host, port=args.port, log_level="info", lifespan="on")
    server = uvicorn.Server(config)
    await server.serve()
    
    # Cleanup
    await daemon.parar()


_daemon_instance = HarmoniaDaemon()
app = _daemon_instance.app


if __name__ == "__main__":
    asyncio.run(main())