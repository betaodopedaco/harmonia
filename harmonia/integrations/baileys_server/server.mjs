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
            
            if (ALLOWED_NUMBERS.length > 0 && !ALLOWED_NUMBERS.includes(from)) {
                console.log('[Baileys] Número não autorizado:', from);
                continue;
            }
            
            const text = msg.message.conversation || 
                         msg.message.extendedTextMessage?.text || '';
            
            if (text) {
                await processarMensagemRecebida(from, text, msg.key.id);
            }
            
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

app.listen(PORT, () => {
    console.log(`[Baileys] Servidor rodando na porta ${PORT}`);
    connectToWhatsApp();
});

export default app;
