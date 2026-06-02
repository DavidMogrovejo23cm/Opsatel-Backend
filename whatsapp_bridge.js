const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const express = require('express');
const { execSync, statSync } = require('child_process');
const fs = require('fs');

const app = express();
const port = process.env.PORT || 3001;

app.use(express.json());

let clientStatus = 'INITIALIZING'; // INITIALIZING, QR_READY, CONNECTED, DISCONNECTED
let activeQrCode = null; // Base64 Data URL for the QR code image

// --- Detección automática del ejecutable de Chromium ---
function getChromiumPath() {
    // 1. Variable de entorno explícita (Railway, Docker, VPS)
    if (process.env.PUPPETEER_EXECUTABLE_PATH) {
        return process.env.PUPPETEER_EXECUTABLE_PATH;
    }
    // 2. Rutas comunes en sistemas Linux / Nix (Railway nixpacks)
    const candidates = [
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/nix/var/nix/profiles/default/bin/chromium',
        '/run/current-system/sw/bin/chromium',
    ];
    for (const p of candidates) {
        try { fs.statSync(p); return p; } catch (_) {}
    }
    // 3. Buscar en PATH
    try { return execSync('which chromium chromium-browser 2>/dev/null | head -1', { encoding: 'utf8' }).trim() || undefined; } catch (_) {}
    return undefined;
}

const chromiumExecutablePath = getChromiumPath();
console.log(`[WhatsApp Bridge] Chromium ejecutable: ${chromiumExecutablePath || 'Puppeteer bundled'}`);

const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: './.wwebjs_auth'
    }),
    puppeteer: {
        headless: true,
        executablePath: chromiumExecutablePath,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--single-process',
            '--disable-gpu'
        ]
    }
});

// QR Code Event
client.on('qr', async (qr) => {
    clientStatus = 'QR_READY';
    console.log('\n--- ESCANEA ESTE CÓDIGO QR EN TU WHATSAPP ---');
    qrcodeTerminal.generate(qr, { small: true });
    console.log('--------------------------------------------\n');

    try {
        // Generate QR code as Base64 Image Data URL
        activeQrCode = await QRCode.toDataURL(qr);
    } catch (err) {
        console.error('Error al generar la imagen Base64 del QR:', err);
    }
});

// Authentication Successful
client.on('authenticated', () => {
    console.log('[WhatsApp] Autenticado correctamente.');
});

// Auth Failure
client.on('auth_failure', (msg) => {
    clientStatus = 'DISCONNECTED';
    activeQrCode = null;
    console.error('[WhatsApp] Fallo de autenticación:', msg);
});

// Ready Event
client.on('ready', () => {
    clientStatus = 'CONNECTED';
    activeQrCode = null;
    console.log('[WhatsApp] Conexión establecida y lista para enviar mensajes.');
});

// Disconnected Event
client.on('disconnected', (reason) => {
    clientStatus = 'DISCONNECTED';
    activeQrCode = null;
    console.log('[WhatsApp] Cliente desconectado:', reason);
    // Attempt reinitialization after a delay
    setTimeout(() => {
        console.log('[WhatsApp] Intentando reconectar...');
        client.initialize().catch(err => console.error('Error al reinicializar:', err));
    }, 10000);
});

// Webhook to send incoming messages to FastAPI (SAM Chatbot)
function sendWebhook(from, body) {
    const http = require('http');
    const payload = JSON.stringify({ numero: from, mensaje: body });
    const options = {
        hostname: 'localhost',
        port: 8000,
        path: '/whatsapp/webhook-mensaje',
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(payload)
        }
    };

    console.log(`[Webhook] Enviando mensaje a FastAPI de ${from}: ${body.substring(0, 30)}...`);
    const req = http.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => data += chunk);
        res.on('end', () => {
            console.log(`[Webhook] Respuesta de FastAPI (${res.statusCode}): ${data}`);
        });
    });

    req.on('error', (e) => {
        console.error(`[Webhook] Error conectando a FastAPI: ${e.message}`);
    });

    req.write(payload);
    req.end();
}

// Incoming Message Event
client.on('message', async (msg) => {
    if (msg.isStatus) return;
    if (msg.fromMe) return;
    if (client.info && client.info.wid && msg.from === client.info.wid._serialized) return;
    if (msg.from.endsWith('@g.us')) return; // Ignore group chats

    // Send only text messages
    if (msg.type === 'chat' && msg.body) {
        sendWebhook(msg.from, msg.body);
    }
});

// --- API Endpoints ---

// Get Status
app.get('/status', (req, res) => {
    res.json({
        status: clientStatus,
        connected: clientStatus === 'CONNECTED'
    });
});

// Get QR Code Image
app.get('/qr', (req, res) => {
    if (clientStatus !== 'QR_READY' || !activeQrCode) {
        return res.json({
            status: clientStatus,
            qr: null,
            message: 'El QR no está listo o ya te encuentras conectado.'
        });
    }
    res.json({
        status: clientStatus,
        qr: activeQrCode
    });
});

// Send Message
app.post('/send', async (req, res) => {
    const { number, message } = req.body;

    if (!number || !message) {
        return res.status(400).json({ success: false, error: 'Los campos number y message son obligatorios.' });
    }

    if (clientStatus !== 'CONNECTED') {
        return res.status(503).json({ success: false, error: 'El servicio de WhatsApp no está conectado actualmente.' });
    }

    try {
        // Clean and format phone number
        let cleanNumber = number.toString().replace(/\D/g, '');
        
        // Ecuador specific formatting
        if (cleanNumber.startsWith('0') && cleanNumber.length === 10) {
            cleanNumber = '593' + cleanNumber.substring(1);
        } else if (cleanNumber.length === 9 && !cleanNumber.startsWith('593')) {
            cleanNumber = '593' + cleanNumber;
        }

        // If it does not end with @c.us, add it
        const chatId = cleanNumber.endsWith('@c.us') ? cleanNumber : `${cleanNumber}@c.us`;

        console.log(`[WhatsApp Bridge] Enviando mensaje a: ${chatId}`);
        const response = await client.sendMessage(chatId, message);

        res.json({
            success: true,
            messageId: response.id._serialized
        });
    } catch (err) {
        console.error('[WhatsApp Bridge] Error al enviar mensaje:', err);
        res.status(500).json({
            success: false,
            error: err.message
        });
    }
});

// Initialize Client
console.log('[WhatsApp] Iniciando cliente...');
client.initialize().catch(err => {
    console.error('[WhatsApp] Error durante la inicialización:', err);
});

// Start Express Server
app.listen(port, () => {
    console.log(`[WhatsApp Bridge] Servidor escuchando en http://localhost:${port}`);
});
