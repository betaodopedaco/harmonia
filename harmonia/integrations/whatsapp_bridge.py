from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Any
from pathlib import Path


@dataclass
class WhatsAppConfig:
    """Configuração para WhatsApp Bridge via Baileys (Node.js)."""
    session_name: str = "harmonia"
    baileys_port: int = 3001
    baileys_host: str = "localhost"
    webhook_url: str = ""
    secret_token: str = ""
    allowed_numbers: list[str] = None  # Formato: "5511999999999@s.whatsapp.net"
    session_dir: str = "./whatsapp_session"


class WhatsAppBridge:
    """
    Ponte WhatsApp para aprovações Ligadão/Soninho via Baileys (TypeScript/Node.js).
    
    IMPORTANTE: Baileys roda em Node.js. Este bridge Python gerencia o processo Baileys
    e comunica via HTTP local (porta 3001 padrão).
    
    Recomendação: Use número dedicado (chip pré-pago) - NUNCA seu número principal.
    Risco real de banimento por automação não-oficial do WhatsApp Web.
    
    Mesmo canal para Ligadão/Soninho - só muda o limiar de quando dispara (dial).
    """
    
    def __init__(self, config: WhatsAppConfig):
        self.config = config
        self._baileys_process: Optional[subprocess.Popen] = None
        self._handler_aprovacao: Optional[Callable] = None
        self._client_session: Optional[Any] = None
        
    async def _get_client_session(self):
        """Lazy import aiohttp client session."""
        if self._client_session is None:
            import aiohttp
            self._client_session = aiohttp.ClientSession()
        return self._client_session
    
    async def _baileys_request(self, endpoint: str, method: str = "GET", json_data: dict = None) -> dict:
        """Faz requisição para o servidor Baileys local."""
        session = await self._get_client_session()
        url = f"http://{self.config.baileys_host}:{self.config.baileys_port}{endpoint}"
        
        try:
            if method == "GET":
                async with session.get(url) as resp:
                    return await resp.json()
            elif method == "POST":
                async with session.post(url, json=json_data) as resp:
                    return await resp.json()
        except Exception as e:
            return {"error": str(e), "success": False}
    
    async def iniciar_baileys(self) -> bool:
        """
        Inicia o servidor Baileys (Node.js) como subprocesso.
        
        O servidor Baileys expõe:
        - GET /status - status da conexão
        - POST /send - enviar mensagem
        - POST /send-buttons - enviar mensagem com botões
        - GET /qrcode - QR code para pareamento
        - Webhook para receber mensagens
        """
        baileys_dir = Path(__file__).parent / "baileys_server"
        
        # Verificar se existe o servidor Baileys
        server_file = baileys_dir / "server.js"
        package_json = baileys_dir / "package.json"
        
        if not server_file.exists():
            await self._criar_servidor_baileys(baileys_dir)
        
        # Instalar dependências se necessário
        if not (baileys_dir / "node_modules").exists():
            print("[WhatsAppBridge] Instalando dependências Baileys...")
            proc = await asyncio.create_subprocess_exec(
                "npm", "install",
                cwd=baileys_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
        
        # Iniciar servidor Baileys
        env = os.environ.copy()
        env.update({
            "BAILEYS_PORT": str(self.config.baileys_port),
            "SESSION_NAME": self.config.session_name,
            "SESSION_DIR": self.config.session_dir,
            "WEBHOOK_URL": self.config.webhook_url,
            "SECRET_TOKEN": self.config.secret_token,
            "ALLOWED_NUMBERS": json.dumps(self.config.allowed_numbers or []),
        })
        
        self._baileys_process = await asyncio.create_subprocess_exec(
            "node", "server.js",
            cwd=baileys_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Aguardar servidor subir
        for _ in range(30):
            await asyncio.sleep(1)
            status = await self._baileys_request("/status")
            if status.get("connected"):
                print("[WhatsAppBridge] Baileys conectado!")
                return True
            elif status.get("qrcode"):
                print(f"[WhatsAppBridge] QR Code disponível em http://{self.config.baileys_host}:{self.config.baileys_port}/qrcode")
        
        return False
    
    async def _criar_servidor_baileys(self, baileys_dir: Path):
        """Cria o servidor Baileys TypeScript/Node.js."""
        baileys_dir.mkdir(parents=True, exist_ok=True)
        
        # package.json
        package_json = {
            "name": "harmonia-baileys-bridge",
            "version": "1.0.0",
            "type": "module",
            "main": "server.js",
            "scripts": {
                "start": "node server.js",
                "dev": "node --watch server.js"
            },
            "dependencies": {
                "@whiskeysockets/baileys": "^6.7.0",
                "express": "^4.18.0",
                "qrcode-terminal": "^0.12.0",
                "pino": "^8.17.0",
                "pino-pretty": "^10.3.0"
            }
        }
        
        (baileys_dir / "package.json").write_text(json.dumps(package_json, indent=2))
        
        # server.js - Servidor Baileys com Express
        server_js = '''
import express from 'express';
import { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, makeCacheableSignalKeyStore } from '@whiskeysockets/baileys';
import pino from 'pino';
import QRCode from 'qrcode-terminal';
import fs from 'fs';
import path from 'path';

const app = express();
app.use(express.json());

const PORT = process.env.BAILEYS_PORT || 3001;
const SESSION_NAME = process.env.SESSION_NAME || 'harmonia';
const SESSION_DIR = process.env.SESSION_DIR || './whatsapp_session';
const WEBHOOK_URL = process.env.WEBHOOK_URL || '';
const SECRET_TOKEN = process.env.SECRET_TOKEN || '';
const ALLOWED_NUMBERS = JSON.parse(process.env.ALLOWED_NUMBERS || '[]');

let sock = null;
let connectionStatus = 'disconnected';
let currentQR = null;

const logger = pino({ level: 'silent' });

async function connectToWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
    const { version, isLatest } = await fetchLatestBaileysVersion();
    
    sock = makeWASocket({
        version,
        logger,
        printQRInTerminal: false,
        auth: {
            creds: state.creds,
            keys: makeCacheableSignalKeyStore(state.keys, logger),
        },
        generateHighQualityLinkPreview: true,
    });

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr !== undefined) {
            currentQR = qr;
            QRCode.generate(qr, { small: true });
            connectionStatus = 'qrcode';
            console.log('[Baileys] QR Code gerado - escaneie com WhatsApp');
        }
        
        if (connection === 'open') {
            connectionStatus = 'connected';
            currentQR = null;
            console.log('[Baileys] Conectado ao WhatsApp!');
        }
        
        if (connection === 'close') {
            connectionStatus = 'disconnected';
            const shouldReconnect = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('[Baileys] Desconectado, reconectando:', shouldReconnect);
            if (shouldReconnect) {
                setTimeout(connectToWhatsApp, 5000);
            }
        }
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;
        
        for (const msg of messages) {
            if (!msg.message || msg.key.fromMe) continue;
            
            const from = msg.key.remoteJid;
            
            // Verificar se número permitido
            if (ALLOWED_NUMBERS.length > 0 && !ALLOWED_NUMBERS.includes(from)) {
                console.log('[Baileys] Número não autorizado:', from);
                continue;
            }
            
            // Processar mensagem de texto
            const text = msg.message.conversation || 
                         msg.message.extendedTextMessage?.text || '';
            
            if (text) {
                await processarMensagemRecebida(from, text, msg.key.id);
            }
            
            // Processar botões de resposta (listResponseMessage, buttonsResponseMessage)
            if (msg.message.buttonsResponseMessage) {
                const buttonId = msg.message.buttonsResponseMessage.selectedButtonId;
                await processarBotaoResposta(from, buttonId, msg.key.id);
            }
            
            if (msg.message.listResponseMessage) {
                const listId = msg.message.listResponseMessage.singleSelectReply.selectedRowId;
                await processarBotaoResposta(from, listId, msg.key.id);
            }
        }
    });
}

async function processarMensagemRecebida(from, text, messageId) {
    console.log('[Baileys] Mensagem recebida de', from, ':', text);
    
    // Encaminhar para webhook do Harmonia se configurado
    if (WEBHOOK_URL) {
        try {
            await fetch(WEBHOOK_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Secret-Token': SECRET_TOKEN,
                },
                body: JSON.stringify({
                    type: 'message',
                    from,
                    text,
                    messageId,
                    timestamp: Date.now(),
                }),
            });
        } catch (e) {
            console.error('[Baileys] Erro no webhook:', e);
        }
    }
}

async function processarBotaoResposta(from, buttonId, messageId) {
    console.log('[Baileys] Botão pressionado:', buttonId, 'de', from);
    
    if (WEBHOOK_URL) {
        try {
            await fetch(WEBHOOK_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Secret-Token': SECRET_TOKEN,
                },
                body: JSON.stringify({
                    type: 'button_response',
                    from,
                    buttonId,
                    messageId,
                    timestamp: Date.now(),
                }),
            });
        } catch (e) {
            console.error('[Baileys] Erro no webhook botão:', e);
        }
    }
}

// API REST
app.get('/status', (req, res) => {
    res.json({
        connected: connectionStatus === 'connected',
        status: connectionStatus,
        qrcode: currentQR,
    });
});

app.get('/qrcode', (req, res) => {
    if (currentQR) {
        res.set('Content-Type', 'image/svg+xml');
        // Retorna QR como SVG simples
        res.send(`<svg>QR Code: ${currentQR}</svg>`);
    } else {
        res.status(404).json({ error: 'QR code não disponível' });
    }
});

app.post('/send', async (req, res) => {
    if (!sock || connectionStatus !== 'connected') {
        return res.status(503).json({ error: 'WhatsApp não conectado' });
    }
    
    const { to, text } = req.body;
    if (!to || !text) {
        return res.status(400).json({ error: 'to e text obrigatórios' });
    }
    
    try {
        const jid = to.includes('@') ? to : `${to}@s.whatsapp.net`;
        await sock.sendMessage(jid, { text });
        res.json({ success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.post('/send-buttons', async (req, res) => {
    if (!sock || connectionStatus !== 'connected') {
        return res.status(503).json({ error: 'WhatsApp não conectado' });
    }
    
    const { to, text, buttons, footer } = req.body;
    if (!to || !text || !buttons) {
        return res.status(400).json({ error: 'to, text e buttons obrigatórios' });
    }
    
    try {
        const jid = to.includes('@') ? to : `${to}@s.whatsapp.net`;
        const buttonMessages = buttons.map((b, i) => ({
            buttonId: b.id || `btn_${i}`,
            buttonText: { displayText: b.text },
            type: 1,
        }));
        
        await sock.sendMessage(jid, {
            text,
            footer: footer || 'Harmonia',
            buttons: buttonMessages,
            headerType: 1,
        });
        res.json({ success: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Iniciar servidor
app.listen(PORT, () => {
    console.log(`[Baileys] Servidor rodando na porta ${PORT}`);
    connectToWhatsApp();
});

export default app;
'''
        
        (baileys_dir / "server.js").write_text(server_js)
        print(f"[WhatsAppBridge] Servidor Baileys criado em {baileys_dir}")
    
    async def enviar_solicitacao_aprovacao(
        self,
        solicitacao_id: str,
        mensagem: str,
        confirmacao_qualificada: bool = False,
        numero_destino: str = None,
    ) -> bool:
        """
        Envia solicitação de aprovação via WhatsApp com botões.
        
        Para alto risco (confirmacao_qualificada=True):
        - Botão "Aprovar" exige resposta digitando resumo depois
        """
        if not numero_destino and self.config.allowed_numbers:
            numero_destino = self.config.allowed_numbers[0]
        
        if not numero_destino:
            print("[WhatsAppBridge] Nenhum número de destino configurado")
            return False
        
        botoes = [
            {"id": f"aprovar:{solicitacao_id}", "text": "✅ Aprovar"},
            {"id": f"rejeitar:{solicitacao_id}", "text": "❌ Rejeitar"},
        ]
        
        if confirmacao_qualificada:
            mensagem += "\n\n⚠️ *Confirmação qualificada:* Após clicar 'Aprovar', digite o resumo da ação para confirmar."
        
        resultado = await self._baileys_request("/send-buttons", "POST", {
            "to": numero_destino,
            "text": mensagem,
            "buttons": botoes,
            "footer": "Harmonia - Aprovação Necessária",
        })
        
        return resultado.get("success", False)
    
    async def enviar_imagem_relatorio(self, caminho_imagem: str, legenda: str, numero_destino: str = None) -> bool:
        """Envia imagem/relatório via WhatsApp."""
        if not numero_destino and self.config.allowed_numbers:
            numero_destino = self.config.allowed_numbers[0]
        
        if not numero_destino:
            return False
        
        # Baileys suporta envio de mídia - implementar se necessário
        # Por enquanto, só texto
        return await self._baileys_request("/send", "POST", {
            "to": numero_destino,
            "text": f"{legenda}\n\n📎 Imagem: {caminho_imagem}",
        })
    
    def registrar_handler_aprovacao(self, handler: Callable):
        """Registra callback para processar respostas de aprovação (via webhook)."""
        self._handler_aprovacao = handler
    
    async def processar_webhook(self, payload: dict) -> dict | None:
        """
        Processa webhook recebido do servidor Baileys.
        Retorna dict padronizado para o grafo LangGraph.
        """
        if payload.get("type") == "button_response":
            button_id = payload.get("buttonId", "")
            from_number = payload.get("from", "")
            
            if button_id.startswith("aprovar:") or button_id.startswith("rejeitar:"):
                acao_id = button_id.split(":", 1)[1]
                aprovado = button_id.startswith("aprovar:")
                
                if self._handler_aprovacao:
                    await self._handler_aprovacao(acao_id, aprovado, from_number)
                
                return {
                    "tipo": "aprovacao",
                    "acao_id": acao_id,
                    "aprovado": aprovado,
                    "from": from_number,
                }
        
        elif payload.get("type") == "message":
            text = payload.get("text", "")
            from_number = payload.get("from", "")
            
            # Confirmação qualificada: usuário digitou resumo após clicar aprovar
            if self._handler_aprovacao and text:
                return {
                    "tipo": "mensagem",
                    "text": text,
                    "from": from_number,
                }
        
        return None
    
    async def fechar(self):
        """Fecha conexões e mata processo Baileys."""
        if self._client_session:
            await self._client_session.close()
        
        if self._baileys_process:
            self._baileys_process.terminate()
            try:
                await asyncio.wait_for(self._baileys_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._baileys_process.kill()


async def criar_bridge_do_env() -> WhatsAppBridge:
    """Cria WhatsAppBridge a partir de variáveis de ambiente."""
    config = WhatsAppConfig(
        session_name=os.getenv("WHATSAPP_SESSION_NAME", "harmonia"),
        baileys_port=int(os.getenv("WHATSAPP_BAILEYS_PORT", "3001")),
        baileys_host=os.getenv("WHATSAPP_BAILEYS_HOST", "localhost"),
        webhook_url=os.getenv("WHATSAPP_WEBHOOK_URL", ""),
        secret_token=os.getenv("WHATSAPP_SECRET_TOKEN", ""),
        allowed_numbers=[x.strip() for x in os.getenv("WHATSAPP_ALLOWED_NUMBERS", "").split(",") if x.strip()],
        session_dir=os.getenv("WHATSAPP_SESSION_DIR", "./whatsapp_session"),
    )
    return WhatsAppBridge(config)