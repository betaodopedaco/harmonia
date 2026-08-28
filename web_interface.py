from __future__ import annotations

import asyncio
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# Importar Harmonia
import sys
sys.path.insert(0, str(Path(__file__).parent))

from harmonia.graph.state import HarmoniaState, DialAutonomia, AcaoProposta, Fundamento, EtapaPlano
from harmonia.graph.build import compilar_sem_checkpoint, criar_estado_inicial
from harmonia.integrations import criar_comunicacao_do_env, ComunicacaoConfig

app = FastAPI(title="Harmonia Web Interface", version="1.0.0")

# Estado global
harmonia_graph = None
estado_atual: Optional[HarmoniaState] = None
comunicacao = None
ws_connections: list[WebSocket] = []
plano_executando = False


class PlanoRequest(BaseModel):
    fundamentos: list[dict]
    etapas: list[dict]
    dial: str = "soninho"


class AcaoResponse(BaseModel):
    id: str
    tipo: str
    descricao: str
    risco: str
    status: str
    resultado: Optional[dict] = None
    erro: Optional[str] = None


def criar_plano_exemplo() -> dict:
    """Plano de exemplo para teste rápido."""
    return {
        "fundamentos": [
            {"id": "f1", "descricao": "Qualidade do código: testes devem passar", "prioridade": 1},
            {"id": "f2", "descricao": "Tempo: execução em menos de 5 minutos", "prioridade": 2},
            {"id": "f3", "descricao": "Custo: zero custo adicional", "prioridade": 3},
        ],
        "etapas": [
            {
                "descricao": "Criar calculadora básica",
                "fundamentos_ids": ["f1", "f2", "f3"],
                "acoes_propostas": [
                    {
                        "tipo": "editar_arquivo",
                        "descricao": "Criar arquivo calculadora.py com funções soma, subtrai, multiplica, divide",
                        "parametros": {"fundamentos_ids": ["f1", "f2", "f3"]},
                        "raciocinio": "Base do sistema - operações matemáticas básicas",
                        "impacto_estimado": "Arquivo novo, baixo risco",
                        "reversivel": True,
                    },
                    {
                        "tipo": "editar_arquivo",
                        "descricao": "Criar testes unitários para calculadora em test_calculadora.py",
                        "parametros": {"fundamentos_ids": ["f1", "f2", "f3"]},
                        "raciocinio": "Garantir qualidade via testes automatizados",
                        "impacto_estimado": "Arquivo de teste, baixo risco",
                        "reversivel": True,
                    },
                    {
                        "tipo": "rodar_testes",
                        "descricao": "Executar testes e confirmar que passam",
                        "parametros": {"fundamentos_ids": ["f1", "f2", "f3"]},
                        "raciocinio": "Validar fundamento de qualidade",
                        "impacto_estimado": "Comando read-only, baixo risco",
                        "reversivel": True,
                    },
                ],
            }
        ],
    }


@app.on_event("startup")
async def startup():
    global harmonia_graph, comunicacao
    
    # Compilar grafo
    harmonia_graph = compilar_sem_checkpoint()
    
    # Inicializar comunicação
    config = ComunicacaoConfig(
        telegram_enabled=False,
        whatsapp_enabled=os.getenv("WHATSAPP_ENABLED", "true").lower() == "true",
        whatsapp_session_name=os.getenv("WHATSAPP_SESSION_NAME", "harmonia"),
        whatsapp_baileys_port=int(os.getenv("WHATSAPP_BAILEYS_PORT", "3001")),
        whatsapp_baileys_host=os.getenv("WHATSAPP_BAILEYS_HOST", "localhost"),
        whatsapp_webhook_url=os.getenv("WHATSAPP_WEBHOOK_URL", ""),
        whatsapp_secret_token=os.getenv("WHATSAPP_SECRET_TOKEN", ""),
        whatsapp_allowed_numbers=[x.strip() for x in os.getenv("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if x.strip()],
        whatsapp_session_dir=os.getenv("WHATSAPP_SESSION_DIR", "./whatsapp_session"),
        voice_enabled=False,
    )
    
    try:
        comunicacao = await criar_comunicacao_do_env()
        # Override com config acima se needed
        print("[WebInterface] Comunicação inicializada")
    except Exception as e:
        print(f"[WebInterface] Aviso: comunicação não inicializada: {e}")
    
    # Registrar handler de aprovação
    if comunicacao:
        comunicacao.registrar_handler_aprovacao(on_aprovacao_recebida)
    
    print("[WebInterface] Startup completo")


async def on_aprovacao_recebida(acao_id: str, aprovado: bool, origem: str, motivo: str = ""):
    """Callback quando aprovação chega (WhatsApp, Telegram, Voz, ou Web)."""
    global estado_atual
    
    if not estado_atual:
        return
    
    # Encontrar a ação na fila
    for solicitacao in estado_atual.fila_aprovacao:
        if solicitacao.acao_id == acao_id and solicitacao.status == "pendente":
            solicitacao.resposta = "aprovado" if aprovado else "rejeitado"
            solicitacao.respondido_em = datetime.now()
            solicitacao.status = "respondida"
            
            if aprovado:
                # Reativar a ação
                for acao in estado_atual.acoes_pendentes:
                    if acao.id == acao_id:
                        acao.status = "pendente"
                        break
            else:
                acao = next((a for a in estado_atual.acoes_pendentes if a.id == acao_id), None)
                if acao:
                    acao.status = "rejeitada"
                    acao.erro = motivo or "Rejeitado pelo usuário"
            
            # Notificar WebSocket
            await broadcast({
                "type": "aprovacao_resultado",
                "acao_id": acao_id,
                "aprovado": aprovado,
                "origem": origem,
            })
            break


async def broadcast(msg: dict):
    """Envia mensagem para todos WebSocket conectados."""
    for ws in ws_connections[:]:
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            ws_connections.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_connections.append(websocket)
    
    # Enviar estado inicial
    await websocket.send_text(json.dumps({
        "type": "estado_inicial",
        "estado": serializar_estado(estado_atual) if estado_atual else None,
    }))
    
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            
            if msg.get("type") == "aprovar":
                await on_aprovacao_recebida(msg["acao_id"], True, "web")
            elif msg.get("type") == "rejeitar":
                await on_aprovacao_recebida(msg["acao_id"], False, "web", msg.get("motivo", ""))
            elif msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_connections.remove(websocket)


def serializar_estado(state: Optional[HarmoniaState]) -> dict:
    if not state:
        return {}
    
    return {
        "plano_id": state.plano_id,
        "dial": state.dial_autonomia.value,
        "acoes_pendentes": [
            {
                "id": a.id,
                "tipo": a.tipo,
                "descricao": a.descricao,
                "risco": a.risco.value,
                "status": a.status.value,
                "raciocinio": a.raciocinio,
                "impacto_estimado": a.impacto_estimado,
                "reversivel": a.reversivel,
            }
            for a in state.acoes_pendentes
        ],
        "acoes_executadas": [
            {
                "id": a.id,
                "tipo": a.tipo,
                "descricao": a.descricao,
                "status": a.status.value,
                "resultado": a.resultado,
                "erro": a.erro,
            }
            for a in state.acoes_executadas
        ],
        "fila_aprovacao": [
            {
                "id": s.id,
                "acao_id": s.acao_id,
                "mensagem": s.mensagem,
                "status": s.status,
                "confirmacao_qualificada": s.confirmacao_qualificada,
            }
            for s in state.fila_aprovacao
        ],
        "criterio_parada_seguranca": state.criterio_parada_seguranca,
        "mensagem_final": state.mensagem_final,
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_INTERFACE


@app.get("/api/estado")
async def api_estado():
    return JSONResponse(serializar_estado(estado_atual))


@app.post("/api/plano/novo")
async def api_plano_novo(plano: PlanoRequest):
    global estado_atual, plano_executando
    
    if plano_executando:
        return JSONResponse({"error": "Plano já em execução"}, status_code=400)
    
    dial = DialAutonomia.LIGADAO if plano.dial == "ligadao" else DialAutonomia.SONINHO
    
    estado_atual = criar_estado_inicial(
        plano_id=f"plano-{uuid.uuid4().hex[:8]}",
        fundamentos=plano.fundamentos,
        etapas=plano.etapas,
        dial=dial,
    )
    
    plano_executando = True
    asyncio.create_task(executar_plano(estado_atual))
    
    await broadcast({"type": "plano_iniciado", "estado": serializar_estado(estado_atual)})
    
    return JSONResponse({"status": "iniciado", "plano_id": estado_atual.plano_id})


@app.post("/api/plano/exemplo")
async def api_plano_exemplo():
    plano = criar_plano_exemplo()
    return await api_plano_novo(PlanoRequest(**plano))


@app.post("/api/aprovar/{acao_id}")
async def api_aprovar(acao_id: str, confirmacao: Optional[str] = Form(None)):
    await on_aprovacao_recebida(acao_id, True, "web", confirmacao or "")
    return JSONResponse({"status": "aprovado"})


@app.post("/api/rejeitar/{acao_id}")
async def api_rejeitar(acao_id: str, motivo: str = Form("")):
    await on_aprovacao_recebida(acao_id, False, "web", motivo)
    return JSONResponse({"status": "rejeitado"})


async def executar_plano(state: HarmoniaState):
    global plano_executando, estado_atual
    
    try:
        # Rodar grafo step by step para permitir interrupção
        config = {"configurable": {"thread_id": state.plano_id}}
        
        async for chunk in harmonia_graph.astream(state, config=config):
            # chunk é dict com node_name -> new_state
            for node_name, new_state in chunk.items():
                if isinstance(new_state, HarmoniaState):
                    estado_atual = new_state
                    await broadcast({
                        "type": "estado_atualizado",
                        "node": node_name,
                        "estado": serializar_estado(new_state),
                    })
                    
                    # Se parou por segurança ou fim
                    if new_state.criterio_parada_seguranca or not new_state.acoes_pendentes:
                        plano_executando = False
                        await broadcast({
                            "type": "plano_finalizado",
                            "estado": serializar_estado(new_state),
                            "mensagem": new_state.mensagem_final or "Concluído",
                        })
                        return
        
        plano_executando = False
        
    except Exception as e:
        plano_executando = False
        await broadcast({
            "type": "erro",
            "mensagem": str(e),
        })


# ============================================================
# HTML INTERFACE
# ============================================================

HTML_INTERFACE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Harmonia — Interface Web</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0d1117; color: #e6edf3; min-height: 100vh; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #30363d; }
        h1 { font-size: 1.5rem; font-weight: 600; }
        .status-badge { padding: 4px 12px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }
        .status-parado { background: #30363d; color: #8b949e; }
        .status-rodando { background: #1f6feb20; color: #58a6ff; }
        .status-aprovacao { background: #d2992220; color: #d29922; }
        .status-concluido { background: #23863620; color: #3fb950; }
        .status-erro { background: #da363320; color: #f85149; }

        .grid { display: grid; grid-template-columns: 1fr 380px; gap: 20px; }
        @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }

        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
        .card h2 { font-size: 0.875rem; font-weight: 600; margin-bottom: 16px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }

        .btn { padding: 10px 16px; border: none; border-radius: 6px; font-size: 0.875rem; font-weight: 500; cursor: pointer; transition: all 0.15s; }
        .btn-primary { background: #238636; color: white; }
        .btn-primary:hover { background: #2ea043; }
        .btn-danger { background: #da3633; color: white; }
        .btn-danger:hover { background: #f85149; }
        .btn-secondary { background: #21262d; color: #e6edf3; border: 1px solid #30363d; }
        .btn-secondary:hover { background: #30363d; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-group { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }

        .acao-item { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; margin-bottom: 12px; }
        .acao-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
        .acao-tipo { font-size: 0.75rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; text-transform: uppercase; }
        .tipo-baixo { background: #23863620; color: #3fb950; }
        .tipo-medio { background: #d2992220; color: #d29922; }
        .tipo-alto { background: #da363320; color: #f85149; }
        .acao-desc { font-size: 0.875rem; line-height: 1.5; color: #e6edf3; }
        .acao-meta { display: flex; gap: 16px; margin-top: 8px; font-size: 0.75rem; color: #8b949e; }
        .acao-raciocinio { margin-top: 8px; padding: 8px; background: #0d1117; border-radius: 4px; font-size: 0.75rem; color: #8b949e; font-style: italic; }

        .aprovacao-box { background: #d2992215; border: 1px solid #d2992240; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
        .aprovacao-box.alto { background: #da363315; border-color: #da363340; }
        .aprovacao-titulo { font-weight: 600; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
        .aprovacao-msg { font-size: 0.875rem; line-height: 1.5; margin-bottom: 12px; white-space: pre-wrap; }
        .aprovacao-btns { display: flex; gap: 8px; }

        .log-container { max-height: 400px; overflow-y: auto; font-family: 'Monaco', 'Menlo', monospace; font-size: 0.75rem; }
        .log-entry { padding: 4px 8px; border-bottom: 1px solid #21262d; display: flex; gap: 8px; }
        .log-time { color: #8b949e; white-space: nowrap; }
        .log-type { color: #58a6ff; font-weight: 500; }
        .log-msg { color: #e6edf3; flex: 1; }

        .dial-selector { display: flex; gap: 8px; margin-bottom: 16px; }
        .dial-btn { flex: 1; padding: 12px; border: 1px solid #30363d; background: #161b22; color: #e6edf3; border-radius: 6px; cursor: pointer; font-weight: 500; }
        .dial-btn.active { border-color: #238636; background: #23863620; color: #3fb950; }
        .dial-btn.ligadao.active { border-color: #d29922; background: #d2992220; color: #d29922; }

        .empty-state { text-align: center; padding: 40px 20px; color: #8b949e; }
        .empty-state svg { width: 64px; height: 64px; margin-bottom: 16px; opacity: 0.5; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 Harmonia</h1>
            <span id="statusBadge" class="status-badge status-parado">Parado</span>
        </header>

        <div class="grid">
            <!-- Painel Principal -->
            <div>
                <div class="card">
                    <h2>Plano Ativo</h2>
                    <div class="dial-selector" id="dialSelector">
                        <button class="dial-btn" data-dial="soninho" onclick="selecionarDial('soninho')">😴 Soninho</button>
                        <button class="dial-btn ligadao" data-dial="ligadao" onclick="selecionarDial('ligadao')">🔥 Ligadão</button>
                    </div>
                    <div class="btn-group">
                        <button class="btn btn-primary" onclick="carregarExemplo()">▶ Carregar Exemplo</button>
                        <button class="btn btn-secondary" onclick="carregarPlanoCustom()">📝 Plano Custom</button>
                    </div>
                    <div id="planoAtivo"></div>
                </div>

                <div class="card" style="margin-top: 20px;">
                    <h2>⏳ Fila de Aprovação</h2>
                    <div id="filaAprovacao">
                        <div class="empty-state">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/>
                                <path d="M12 6v6l4 2"/>
                            </svg>
                            <p>Nenhuma aprovação pendente</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Painel Lateral -->
            <div>
                <div class="card">
                    <h2>📋 Ações Executadas</h2>
                    <div id="acoesExecutadas">
                        <div class="empty-state">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
                            </svg>
                            <p>Nenhuma ação executada</p>
                        </div>
                    </div>
                </div>

                <div class="card" style="margin-top: 20px;">
                    <h2>📡 Log de Eventos</h2>
                    <div class="log-container" id="logContainer">
                        <div class="log-entry"><span class="log-time">[Sistema]</span> <span class="log-type">INFO</span> <span class="log-msg">Interface carregada. Aguardando plano...</span></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let dialAtual = 'soninho';

        function log(msg, type = 'INFO') {
            const container = document.getElementById('logContainer');
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            const now = new Date();
            entry.innerHTML = `<span class="log-time">[${now.toLocaleTimeString()}]</span> <span class="log-type">${type}</span> <span class="log-msg">${msg}</span>`;
            container.insertBefore(entry, container.firstChild);
        }

        function atualizarStatus(status) {
            const badge = document.getElementById('statusBadge');
            badge.className = 'status-badge status-' + status;
            badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        }

        function selecionarDial(dial) {
            dialAtual = dial;
            document.querySelectorAll('.dial-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.dial === dial);
            });
            log(`Dial alterado para: ${dial}`);
        }

        async function carregarExemplo() {
            try {
                const resp = await fetch('/api/plano/exemplo', { method: 'POST' });
                const data = await resp.json();
                log(`Plano exemplo carregado: ${data.plano_id}`);
                atualizarStatus('rodando');
            } catch (e) {
                log('Erro ao carregar exemplo: ' + e, 'ERROR');
            }
        }

        async function carregarPlanoCustom() {
            // TODO: abrir modal para plano custom
            alert('Funcionalidade em breve. Use o exemplo por enquanto.');
        }

        function renderPlano(estado) {
            const container = document.getElementById('planoAtivo');
            if (!estado || !estado.acoes_pendentes.length && !estado.acoes_executadas.length) {
                container.innerHTML = '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg><p>Nenhum plano ativo. Clique em "Carregar Exemplo".</p></div>';
                return;
            }

            let html = '';
            if (estado.acoes_pendentes.length) {
                html += '<h3 style="margin-bottom:12px;color:#d29922;">⏳ Pendentes</h3>';
                estado.acoes_pendentes.forEach(a => {
                    html += renderAcao(a);
                });
            }
            if (estado.acoes_executadas.length) {
                html += '<h3 style="margin:20px 0 12px;color:#3fb950;">✅ Executadas</h3>';
                estado.acoes_executadas.forEach(a => {
                    html += renderAcao(a);
                });
            }
            container.innerHTML = html;
        }

        function renderAcao(a) {
            return `
                <div class="acao-item">
                    <div class="acao-header">
                        <span class="acao-tipo tipo-${a.risco}">${a.risco}</span>
                        <span>${a.tipo}</span>
                    </div>
                    <div class="acao-desc">${a.descricao}</div>
                    <div class="acao-meta">
                        <span>Status: ${a.status}</span>
                        ${a.reversivel ? '<span>↩️ Reversível</span>' : '<span>⚠️ Irreversível</span>'}
                    </div>
                    ${a.raciocinio ? `<div class="acao-raciocinio">${a.raciocinio}</div>` : ''}
                </div>
            `;
        }

        function renderFilaAprovacao(estado) {
            const container = document.getElementById('filaAprovacao');
            if (!estado || !estado.fila_aprovacao.length) {
                container.innerHTML = '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="M12 6v6l4 2"/></svg><p>Nenhuma aprovação pendente</p></div>';
                return;
            }

            let html = '';
            estado.fila_aprovacao.forEach(s => {
                const isAlto = s.confirmacao_qualificada;
                html += `
                    <div class="aprovacao-box ${isAlto ? 'alto' : ''}">
                        <div class="aprovacao-titulo">
                            ${isAlto ? '⚠️ ALTO RISCO - Confirmação Qualificada' : '📋 Aprovação Necessária'}
                        </div>
                        <div class="aprovacao-msg">${s.mensagem}</div>
                        <div class="aprovacao-btns">
                            <button class="btn btn-primary" onclick="aprovar('${s.acao_id}')">✅ Aprovar</button>
                            <button class="btn btn-danger" onclick="rejeitar('${s.acao_id}')">❌ Rejeitar</button>
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html;
        }

        function renderAcoesExecutadas(estado) {
            const container = document.getElementById('acoesExecutadas');
            if (!estado || !estado.acoes_executadas.length) {
                container.innerHTML = '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg><p>Nenhuma ação executada</p></div>';
                return;
            }

            let html = '';
            [...estado.acoes_executadas].reverse().forEach(a => {
                const statusIcon = a.status === 'concluida' ? '✅' : '❌';
                html += `
                    <div class="acao-item">
                        <div class="acao-header">
                            <span>${statusIcon} ${a.tipo}</span>
                            <span class="acao-tipo tipo-${a.risco}">${a.risco}</span>
                        </div>
                        <div class="acao-desc">${a.descricao}</div>
                        ${a.erro ? `<div style="color:#f85149;margin-top:8px;font-size:0.75rem;">Erro: ${a.erro}</div>` : ''}
                        ${a.resultado ? `<div class="acao-raciocinio">Resultado: ${JSON.stringify(a.resultado).slice(0,200)}...</div>` : ''}
                    </div>
                `;
            });
            container.innerHTML = html;
        }

        async function aprovar(acaoId) {
            try {
                const resp = await fetch(`/api/aprovar/${acaoId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'confirmacao=' + encodeURIComponent(prompt('Confirme digitando o resumo da ação:') || '')
                });
                log(`Ação ${acaoId} aprovada via Web`);
            } catch (e) {
                log('Erro ao aprovar: ' + e, 'ERROR');
            }
        }

        async function rejeitar(acaoId) {
            const motivo = prompt('Motivo da rejeição:') || 'Rejeitado pelo usuário';
            try {
                const resp = await fetch(`/api/rejeitar/${acaoId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'motivo=' + encodeURIComponent(motivo)
                });
                log(`Ação ${acaoId} rejeitada: ${motivo}`);
            } catch (e) {
                log('Erro ao rejeitar: ' + e, 'ERROR');
            }
        }

        // WebSocket
        function conectarWS() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => log('WebSocket conectado');
            ws.onclose = () => { log('WebSocket desconectado, reconectando...', 'WARN'); setTimeout(conectarWS, 3000); };
            ws.onerror = (e) => log('WebSocket erro: ' + e, 'ERROR');

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                handleWSMessage(msg);
            };
        }

        function handleWSMessage(msg) {
            switch (msg.type) {
                case 'estado_inicial':
                case 'estado_atualizado':
                    if (msg.estado) {
                        renderPlano(msg.estado);
                        renderFilaAprovacao(msg.estado);
                        renderAcoesExecutadas(msg.estado);
                    }
                    break;
                case 'plano_iniciado':
                    atualizarStatus('rodando');
                    if (msg.estado) renderPlano(msg.estado);
                    break;
                case 'plano_finalizado':
                    atualizarStatus(msg.estado?.criterio_parada_seguranca ? 'erro' : 'concluido');
                    if (msg.estado) renderPlano(msg.estado);
                    if (msg.mensagem) log(msg.mensagem);
                    break;
                case 'aprovacao_resultado':
                    log(`Aprovação ${msg.aprovado ? '✅' : '❌'} para ${msg.acao_id} (via ${msg.origem})`);
                    break;
                case 'erro':
                    log('Erro: ' + msg.mensagem, 'ERROR');
                    atualizarStatus('erro');
                    break;
            }
        }

        // Inicializar
        conectarWS();
        log('Interface pronta. Selecione o dial e carregue um plano.');

        // Polling fallback para estado (caso WS falhe)
        setInterval(async () => {
            try {
                const resp = await fetch('/api/estado');
                const estado = await resp.json();
                if (estado && estado.plano_id) {
                    renderPlano(estado);
                    renderFilaAprovacao(estado);
                    renderAcoesExecutadas(estado);
                }
            } catch (e) {}
        }, 5000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)