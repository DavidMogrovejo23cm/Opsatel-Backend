const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const express = require('express');

const app = express();
const port = process.env.PORT || 3001;

app.use(express.json());

let clientStatus = 'INITIALIZING'; // INITIALIZING, QR_READY, CONNECTED, DISCONNECTED
let activeQrCode = null; // Base64 Data URL for the QR code image

const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: './.wwebjs_auth'
    }),
    puppeteer: {
        headless: true,
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
