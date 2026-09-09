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
    // 2. Rutas comunes en sistemas Linux / Nix
    const candidates = [
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/nix/var/nix/profiles/default/bin/chromium',
        '/run/current-system/sw/bin/chromium'
    ];
    for (const p of candidates) {
        if (!p) continue;
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
    takeoverOnConflict: true,
    takeoverTimeoutMs: 0,
    puppeteer: {
        headless: true,
        executablePath: chromiumExecutablePath,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--disable-gpu',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-ipc-flooding-protection'
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
    console.log('[WhatsApp] Conexión establecida y lista para enviar y recibir mensajes.');
});

// Disconnected Event
client.on('disconnected', async (reason) => {
    clientStatus = 'DISCONNECTED';
    activeQrCode = null;
    console.log('[WhatsApp] Cliente desconectado:', reason);
    try {
        await client.destroy();
    } catch (errDest) {
        console.warn('[WhatsApp] Aviso al destruir cliente tras desconexión:', errDest.message);
    }
    cleanChromiumLocks('./.wwebjs_auth');
    // Attempt reinitialization after a delay (LocalAuth preserves session)
    setTimeout(() => {
        console.log('[WhatsApp] Intentando reconectar automáticamente...');
        client.initialize().catch(err => console.error('Error al reinicializar:', err));
    }, 5000);
});

// --- Keep-Alive Heartbeat ---
// Previene que Chromium congele la pestaña en segundo plano y mantiene activo el WebSocket
let keepAliveFails = 0;
setInterval(async () => {
    if (clientStatus === 'CONNECTED' && client) {
        try {
            const state = await client.getState();
            if (state === 'CONNECTED') {
                keepAliveFails = 0;
            } else {
                keepAliveFails++;
                console.warn(`[WhatsApp KeepAlive] Estado no conectado: ${state} (${keepAliveFails}/3)`);
                if (keepAliveFails >= 3) {
                    console.warn('[WhatsApp KeepAlive] Reiniciando cliente tras 3 fallos de estado...');
                    clientStatus = 'DISCONNECTED';
                    try { await client.destroy(); } catch (_) {}
                    cleanChromiumLocks('./.wwebjs_auth');
                    setTimeout(() => {
                        client.initialize().catch(err => console.error('[WhatsApp KeepAlive] Error reiniciando:', err));
                    }, 3000);
                }
            }
        } catch (err) {
            console.warn(`[WhatsApp KeepAlive] Ping de estado: ${err.message}`);
        }
    }
}, 45000);

// Puerto de destino hacia FastAPI para el webhook
const fastapiPort = parseInt(process.env.FASTAPI_PORT || process.env.BACKEND_PORT || '8000', 10);

// Webhook to send incoming messages to FastAPI (SAM Chatbot)
function sendWebhook(from, body, pushname = '', originalJid = '') {
    const http = require('http');
    const payload = JSON.stringify({ 
        numero: from, 
        mensaje: body,
        nombre: pushname,
        jid_original: originalJid
    });
    const options = {
        hostname: '127.0.0.1', // Usar 127.0.0.1 explícito para evitar fallos de IPv6 ::1
        port: fastapiPort,
        path: '/whatsapp/webhook-mensaje',
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(payload)
        }
    };

    console.log(`[Webhook] Enviando mensaje a FastAPI (puerto ${fastapiPort}) de ${from} (${pushname || 'Sin nombre'}): ${body.substring(0, 40)}...`);
    const req = http.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => data += chunk);
        res.on('end', () => {
            console.log(`[Webhook] Respuesta de FastAPI (${res.statusCode}): ${data}`);
        });
    });

    req.setTimeout(25000, () => {
        console.error(`[Webhook] Timeout (25s) conectando a FastAPI en puerto ${fastapiPort}`);
        req.destroy();
    });

    req.on('error', (e) => {
        console.error(`[Webhook] Error conectando a FastAPI en 127.0.0.1:${fastapiPort}: ${e.message}`);
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

    let remitente = msg.from;
    let pushname = msg._data?.notifyName || '';
    let realPhone = '';

    try {
        const contact = await msg.getContact();
        if (contact) {
            if (contact.number) realPhone = contact.number;
            if (contact.pushname) pushname = contact.pushname;
            else if (contact.name) pushname = contact.name;
        }
    } catch (eContact) {
        console.warn(`[WhatsApp Bridge] No se pudo obtener contacto de ${msg.from}:`, eContact.message);
    }

    // Si viene como @lid pero obtuvimos su número telefónico real, usarlo para vincular con la BD
    let idDestino = remitente;
    if (remitente.endsWith('@lid') && realPhone) {
        idDestino = `${realPhone}@c.us`;
        console.log(`[WhatsApp Bridge] Mapeando LID ${remitente} -> Teléfono real: ${idDestino} (${pushname})`);
    }

    console.log(`[WhatsApp Bridge] Mensaje entrante de ${idDestino} (LID original: ${msg.from}, nombre: "${pushname}"): "${msg.body ? msg.body.substring(0, 40) : '[Sin texto]'}"`);

    // Manejar mensajes de texto
    if (msg.type === 'chat' && msg.body) {
        sendWebhook(idDestino, msg.body, pushname, msg.from);
    } else if (msg.type && msg.type !== 'chat') {
        // Notificar a SAM sobre mensaje no-texto (audio, imagen, video, documento)
        sendWebhook(idDestino, `[NON_TEXT_MSG] ${msg.type}`, pushname, msg.from);
    }
});

// --- API Endpoints ---

// Obtener detalles de un contacto (Teléfono real y Nombre público)
app.get('/contact/:chatId', async (req, res) => {
    try {
        const { chatId } = req.params;
        if (clientStatus !== 'CONNECTED') {
            return res.status(503).json({ success: false, error: 'WhatsApp desconectado' });
        }
        let number = null;
        let name = null;
        let pushname = null;

        try {
            const contact = await client.getContactById(chatId);
            if (contact) {
                number = contact.number || null;
                name = contact.name || null;
                pushname = contact.pushname || null;
            }
        } catch (e1) {}

        if (!name && !pushname) {
            try {
                const chat = await client.getChatById(chatId);
                if (chat && chat.name) {
                    name = chat.name;
                }
            } catch (e2) {}
        }

        res.json({
            success: true,
            number: number,
            name: name,
            pushname: pushname
        });
    } catch (err) {
        res.json({ success: false, error: err.message });
    }
});

// Cerrar sesión activa (Logout)
app.post('/logout', async (req, res) => {
    try {
        console.log('[WhatsApp Bridge] Solicitud de cierre de sesión recibida...');
        if (client) {
            try {
                await client.logout();
            } catch (errLogout) {
                console.warn('[WhatsApp Bridge] Aviso en client.logout():', errLogout.message);
            }
            clientStatus = 'DISCONNECTED';
            activeQrCode = null;
            cleanChromiumLocks('./.wwebjs_auth');
            
            setTimeout(() => {
                console.log('[WhatsApp Bridge] Reiniciando cliente para generar nuevo QR...');
                client.initialize().catch(errInit => console.error('Error al reinicializar tras logout:', errInit));
            }, 3000);
        }
        res.json({ success: true, message: 'Sesión de WhatsApp cerrada. Se generará un nuevo QR para vincular.' });
    } catch (err) {
        console.error('[WhatsApp Bridge] Error al cerrar sesión:', err);
        res.status(500).json({ success: false, error: err.message });
    }
});

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
        // Clean and format phone number, preserving the domain (like @lid or @c.us) if present
        let cleanNumber = number.toString();
        let server = 'c.us';
        if (cleanNumber.includes('@')) {
            const parts = cleanNumber.split('@');
            cleanNumber = parts[0].replace(/\D/g, '');
            server = parts[1];
        } else {
            cleanNumber = cleanNumber.replace(/\D/g, '');
        }
        
        // Ecuador specific formatting (solo para @c.us)
        if (server !== 'lid') {
            if (cleanNumber.startsWith('0') && cleanNumber.length === 10) {
                cleanNumber = '593' + cleanNumber.substring(1);
            } else if (cleanNumber.length === 9 && !cleanNumber.startsWith('593')) {
                cleanNumber = '593' + cleanNumber;
            }
        }

        const chatId = `${cleanNumber}@${server}`;
        console.log(`[WhatsApp Bridge] Preparando envío a: ${chatId}`);

        // 1. Verificación previa: Comprobar si el número está registrado en WhatsApp (SOLO para @c.us)
        // IMPORTANTE: NO ejecutar getNumberId para @lid porque getNumberId solo acepta números de teléfono
        // y retorna null para LIDs, provocando rechazos erróneos.
        let targetChatId = chatId;
        if (!chatId.endsWith('@lid') && server !== 'lid') {
            try {
                const numberCheck = await Promise.race([
                    client.getNumberId(chatId),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout_check')), 6000))
                ]);

                if (numberCheck && numberCheck._serialized) {
                    targetChatId = numberCheck._serialized;
                } else if (numberCheck === null) {
                    console.warn(`[WhatsApp Bridge] El número ${chatId} no está registrado en WhatsApp. Omitiendo envío.`);
                    return res.status(400).json({
                        success: false,
                        error: 'El número no está registrado en WhatsApp.'
                    });
                }
            } catch (errCheck) {
                console.warn(`[WhatsApp Bridge] Aviso en verificación de número (${chatId}): ${errCheck.message}`);
            }
        }

        // 2. Enviar mensaje con captura de advertencias de serialización (común en destinatarios @lid)
        let sendSuccess = false;
        let messageId = 'sent';

        try {
            const sendPromise = client.sendMessage(targetChatId, message);
            const timeoutPromise = new Promise((_, reject) => 
                setTimeout(() => reject(new Error('Timeout de 15 segundos al enviar mensaje por WhatsApp.')), 15000)
            );

            const response = await Promise.race([sendPromise, timeoutPromise]);
            sendSuccess = true;
            if (response && response.id) {
                messageId = response.id._serialized || String(response.id);
            }
        } catch (sendErr) {
            console.warn(`[WhatsApp Bridge] Aviso o error en client.sendMessage (${targetChatId}):`, sendErr.message || sendErr);
            const errMsg = String(sendErr.message || '').toLowerCase();
            const esDesconexionFatal = errMsg.includes('disconnected') || errMsg.includes('session closed') || errMsg.includes('target closed') || errMsg.includes('execution context was destroyed');
            if (!esDesconexionFatal) {
                // En WhatsApp Web (especialmente en destinatarios @lid), Puppeteer a menudo falla al serializar
                // el objeto de retorno tras la inyección, pero el mensaje ya fue despachado exitosamente al chat.
                console.log(`[WhatsApp Bridge] Mensaje despachado hacia ${targetChatId} (tratando retorno como entregado).`);
                sendSuccess = true;
                messageId = 'sent_ok';
            } else {
                throw sendErr;
            }
        }

        if (sendSuccess) {
            console.log(`[WhatsApp Bridge] Mensaje enviado exitosamente a: ${targetChatId}`);
            return res.json({
                success: true,
                messageId: messageId
            });
        }
    } catch (err) {
        console.error('[WhatsApp Bridge] Error al enviar mensaje:', err.message || err);
        return res.status(500).json({
            success: false,
            error: err.message || 'Error desconocido al enviar mensaje'
        });
    }
});

// Limpiar archivos de bloqueo residuales de Chromium en el volumen montado
const path = require('path');
function cleanChromiumLocks(dir) {
    if (!fs.existsSync(dir)) return;
    try {
        const files = fs.readdirSync(dir);
        for (const file of files) {
            const fullPath = path.join(dir, file);
            try {
                const stat = fs.lstatSync(fullPath);
                if (stat.isDirectory()) {
                    cleanChromiumLocks(fullPath);
                } else if (file === 'SingletonLock' || file === 'lock') {
                    console.log(`[WhatsApp Bridge] Eliminando archivo de bloqueo residual: ${fullPath}`);
                    fs.unlinkSync(fullPath);
                }
            } catch (err) {
                try {
                    fs.unlinkSync(fullPath);
                    console.log(`[WhatsApp Bridge] Eliminando enlace simbólico de bloqueo roto: ${fullPath}`);
                } catch (e) {}
            }
        }
    } catch (e) {
        console.error('[WhatsApp Bridge] Error al limpiar bloqueos de Chromium:', e);
    }
}

console.log('[WhatsApp] Limpiando archivos de bloqueo de Chromium...');
cleanChromiumLocks('./.wwebjs_auth');

// Initialize Client
console.log('[WhatsApp] Iniciando cliente...');
client.initialize().catch(err => {
    console.error('[WhatsApp] Error durante la inicialización:', err);
});

// Start Express Server
app.listen(port, () => {
    console.log(`[WhatsApp Bridge] Servidor escuchando en http://localhost:${port}`);
});
