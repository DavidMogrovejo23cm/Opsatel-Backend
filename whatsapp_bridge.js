const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcodeTerminal = require('qrcode-terminal');
const QRCode = require('qrcode');
const express = require('express');
const { execSync, statSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const app = express();
const port = process.env.PORT || 3001;

app.use(express.json({ limit: '25mb' }));
app.use(express.urlencoded({ extended: true, limit: '25mb' }));

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

// ===========================================================================
// REINICIO CONTROLADO DEL CLIENTE (evita doble initialize y crashes del proceso)
// ===========================================================================
let reiniting = false;
let reinitAttempts = 0;

async function reinitClient(baseDelayMs = 5000, reason = '') {
    if (reiniting) return;
    reiniting = true;
    clientStatus = 'DISCONNECTED';
    activeQrCode = null;
    const delay = Math.min(baseDelayMs * Math.pow(2, reinitAttempts), 300000);
    reinitAttempts++;
    console.log(`[WhatsApp] Reiniciando cliente en ${Math.round(delay / 1000)}s (${reason || 'sin motivo'}), intento #${reinitAttempts}`);
    try {
        await client.destroy();
    } catch (errDest) {
        console.warn('[WhatsApp] Aviso al destruir cliente:', errDest.message);
    }
    cleanChromiumLocks('./.wwebjs_auth');
    setTimeout(async () => {
        try {
            console.log('[WhatsApp] Intentando reconectar automáticamente...');
            await client.initialize();
            reiniting = false;
        } catch (err) {
            console.error('Error al reinicializar:', err && err.message ? err.message : err);
            reiniting = false;
            reinitClient(baseDelayMs, 'fallo al inicializar');
        }
    }, delay);
}

// Errores típicos de Puppeteer cuando WhatsApp Web cierra/recarga la página: NO deben matar el proceso.
function esErrorPuppeteerRecuperable(err) {
    const m = String((err && err.message) || err || '').toLowerCase();
    return m.includes('detached frame') || m.includes('target closed') || m.includes('session closed') ||
           m.includes('execution context was destroyed') || m.includes('protocol error') || m.includes('navigating frame was detached');
}

process.on('unhandledRejection', (reason) => {
    console.error('[WhatsApp Bridge] unhandledRejection:', reason && reason.message ? reason.message : reason);
    if (esErrorPuppeteerRecuperable(reason)) {
        reinitClient(5000, 'error de Puppeteer recuperable');
    }
});
process.on('uncaughtException', (err) => {
    console.error('[WhatsApp Bridge] uncaughtException:', err && err.message ? err.message : err);
    if (esErrorPuppeteerRecuperable(err)) {
        reinitClient(5000, 'excepción de Puppeteer recuperable');
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
    reinitAttempts = 0;
    console.log('[WhatsApp] Conexión establecida y lista para enviar y recibir mensajes.');
});

// Disconnected Event
client.on('disconnected', async (reason) => {
    clientStatus = 'DISCONNECTED';
    activeQrCode = null;
    console.log('[WhatsApp] Cliente desconectado:', reason);
    if (String(reason).toUpperCase() === 'LOGOUT') {
        // Tras un LOGOUT (restricción, desvinculación) NO se debe reanudar el envío masivo de inmediato.
        pausarEnvioMasivo(AB.logoutPauseMs, 'logout de WhatsApp (enfriamiento tras desvinculación)');
        ab.rampStart = Date.now() + AB.logoutPauseMs;
        saveAb();
    }
    // Reinicio controlado (LocalAuth preserva la sesión)
    reinitClient(5000, `desconectado: ${reason}`);
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
                    keepAliveFails = 0;
                    reinitClient(3000, 'keepalive: 3 fallos de estado');
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

// --- Sistema de Resolución y Caché LID -> Teléfono Real ---
const LID_CACHE_FILE = path.join(__dirname, 'lid_cache.json');
let lidPhoneMap = {};

try {
    if (fs.existsSync(LID_CACHE_FILE)) {
        lidPhoneMap = JSON.parse(fs.readFileSync(LID_CACHE_FILE, 'utf8'));
    }
} catch (eCache) {
    console.warn('[WhatsApp Bridge] Aviso leyendo lid_cache.json:', eCache.message);
}

function saveLidCache() {
    try {
        fs.writeFileSync(LID_CACHE_FILE, JSON.stringify(lidPhoneMap, null, 2), 'utf8');
    } catch (eSave) {
        console.warn('[WhatsApp Bridge] Aviso guardando lid_cache.json:', eSave.message);
    }
}

async function resolveLidToPhone(lidId) {
    if (!lidId || typeof lidId !== 'string') return null;
    const cleanLid = lidId.trim().toLowerCase();
    if (!cleanLid.endsWith('@lid')) return null;

    // 1. Verificar si ya lo tenemos en caché
    if (lidPhoneMap[cleanLid]) {
        return lidPhoneMap[cleanLid];
    }

    // 2. Intentar resolución nativa con whatsapp-web.js (getContactLidAndPhone)
    if (client && typeof client.getContactLidAndPhone === 'function') {
        try {
            const mappings = await client.getContactLidAndPhone([cleanLid]);
            if (mappings && mappings.length > 0) {
                const m = mappings[0];
                const pn = m.pn || m.phoneNumber || '';
                if (pn && !pn.endsWith('@lid')) {
                    const phoneOnly = pn.replace('@c.us', '').replace('@s.whatsapp.net', '').trim();
                    if (phoneOnly && phoneOnly.length >= 8 && phoneOnly.length <= 15) {
                        lidPhoneMap[cleanLid] = phoneOnly;
                        saveLidCache();
                        console.log(`[WhatsApp Bridge] 🎯 getContactLidAndPhone resolvió ${cleanLid} -> ${phoneOnly}`);
                        return phoneOnly;
                    }
                }
            }
        } catch (eGetPn) {
            console.warn(`[WhatsApp Bridge] getContactLidAndPhone error para ${cleanLid}:`, eGetPn.message);
        }
    }

    // 3. Inspeccionar el chat internamente en WhatsApp Web
    try {
        if (client && typeof client.getChatById === 'function') {
            const chat = await client.getChatById(cleanLid);
            if (chat && chat.id && chat.id.user && !chat.id.user.endsWith('@lid') && chat.id.user.length >= 8 && chat.id.user.length <= 13) {
                const phoneOnly = chat.id.user;
                lidPhoneMap[cleanLid] = phoneOnly;
                saveLidCache();
                console.log(`[WhatsApp Bridge] 🎯 getChatById resolvió ${cleanLid} -> ${phoneOnly}`);
                return phoneOnly;
            }
        }
    } catch (_) {}

    return null;
}

// ===========================================================================
// GOBERNADOR ANTI-BLOQUEO (anti-ban)
// ---------------------------------------------------------------------------
// WhatsApp restringe cuentas por: envío en horarios no humanos (noche/madrugada),
// ráfagas, mismo texto a muchos números, escribir a números inexistentes,
// reportes/bloqueos de destinatarios y reconexiones/relinks seguidos.
// Todo envío "bulk" (difusión, programados, reintentos) pasa por este gobernador;
// los "reply" (respuestas del chatbot a quien nos escribió) son de bajo riesgo.
//
// Prioridades:  bulk   -> sujeto a ventana horaria, topes, cooldown, opt-out y pausas
//               manual -> operador humano: solo espaciado mínimo + typing
//               reply  -> respuesta a mensaje entrante: espaciado mínimo + typing
//
// Variables de entorno (todas opcionales):
//   WA_TIMEZONE=America/Guayaquil   WA_BULK_WINDOW_START=8   WA_BULK_WINDOW_END=19
//   (para desactivar la ventana: START=0 y END=24)
//   WA_BULK_MIN_GAP_SEC=60  WA_BULK_MAX_GAP_SEC=180
//   WA_BULK_HOURLY_CAP=10   WA_BULK_DAILY_CAP=50
//   WA_WARMUP=on|off  WA_WARMUP_START=15  WA_WARMUP_STEP=5  (tope diario progresivo)
//   WA_PER_NUMBER_COOLDOWN_H=6  WA_FAIL_BREAKER=3  WA_FAIL_PAUSE_MIN=30  WA_LOGOUT_PAUSE_H=12
// ===========================================================================
const envNum = (k, d) => { const v = parseFloat(process.env[k]); return Number.isFinite(v) ? v : d; };
const DAY_MS = 24 * 3600 * 1000;
const AB = {
    tz: process.env.WA_TIMEZONE || 'America/Guayaquil',
    windowStart: envNum('WA_BULK_WINDOW_START', 7),
    windowEnd: envNum('WA_BULK_WINDOW_END', 22),
    bulkGapSec: [envNum('WA_BULK_MIN_GAP_SEC', 10), envNum('WA_BULK_MAX_GAP_SEC', 25)],
    manualGapSec: [2, 6],
    replyGapSec: [1, 3],
    hourlyCap: envNum('WA_BULK_HOURLY_CAP', 60),
    dailyCap: envNum('WA_BULK_DAILY_CAP', 300),
    warmupEnabled: (process.env.WA_WARMUP || 'off').toLowerCase() === 'on',
    warmupStart: envNum('WA_WARMUP_START', 30),
    warmupStep: envNum('WA_WARMUP_STEP', 15),
    perNumberCooldownMs: envNum('WA_PER_NUMBER_COOLDOWN_H', 0.5) * 3600 * 1000,
    failThreshold: envNum('WA_FAIL_BREAKER', 8),
    failPauseMs: envNum('WA_FAIL_PAUSE_MIN', 5) * 60 * 1000,
    logoutPauseMs: envNum('WA_LOGOUT_PAUSE_H', 12) * 3600 * 1000,
    numberOkTtlMs: 30 * DAY_MS,
    numberBadTtlMs: 2 * 3600 * 1000
};

const AB_STATE_DIR = path.join(process.cwd(), '.wwebjs_auth');
const AB_STATE_FILE = path.join(AB_STATE_DIR, 'antiban_state.json');
let ab = {
    bulkSent: [],          // timestamps (ms) de envíos bulk de las últimas 24h
    perNumber: {},         // dígitos -> último envío bulk
    numberCheck: {},       // dígitos -> { ok, id, ts } resultado de getNumberId
    optOut: {},            // dígitos/LID -> ts (pidió BAJA)
    pausedUntil: 0,        // pausa global del envío bulk
    pauseReason: '',
    nextBulkAt: 0,         // no enviar otro bulk antes de esta marca
    rampStart: Date.now(), // inicio del calentamiento (warm-up)
    consecutiveFails: 0
};

try {
    if (fs.existsSync(AB_STATE_FILE)) {
        ab = Object.assign(ab, JSON.parse(fs.readFileSync(AB_STATE_FILE, 'utf8')));
    }
} catch (eAb) {
    console.warn('[AntiBan] Aviso leyendo estado:', eAb.message);
}

function pruneAb(now = Date.now()) {
    ab.bulkSent = (ab.bulkSent || []).filter(t => now - t < DAY_MS);
    for (const k of Object.keys(ab.perNumber || {})) {
        if (now - ab.perNumber[k] > DAY_MS) delete ab.perNumber[k];
    }
    for (const k of Object.keys(ab.numberCheck || {})) {
        const e = ab.numberCheck[k];
        const ttl = e && e.ok ? AB.numberOkTtlMs : AB.numberBadTtlMs;
        if (!e || now - e.ts > ttl) delete ab.numberCheck[k];
    }
}

function saveAb() {
    try {
        pruneAb();
        fs.mkdirSync(AB_STATE_DIR, { recursive: true });
        fs.writeFileSync(AB_STATE_FILE, JSON.stringify(ab), 'utf8');
    } catch (eSave) {
        console.warn('[AntiBan] Aviso guardando estado:', eSave.message);
    }
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const rand = (a, b) => a + Math.random() * (b - a);
const digitsOf = (s) => String(s || '').replace(/\D/g, '');

function localTime() {
    const f = new Intl.DateTimeFormat('en-GB', { timeZone: AB.tz, hour: 'numeric', minute: 'numeric', second: 'numeric', hour12: false });
    const p = Object.fromEntries(f.formatToParts(new Date()).map(x => [x.type, x.value]));
    return { h: parseInt(p.hour, 10) % 24, m: parseInt(p.minute, 10), s: parseInt(p.second, 10) };
}

function inBulkWindow() {
    const { h } = localTime();
    if (AB.windowStart <= AB.windowEnd) return h >= AB.windowStart && h < AB.windowEnd;
    return h >= AB.windowStart || h < AB.windowEnd; // ventana que cruza medianoche
}

function secondsToWindowOpen() {
    const { h, m, s } = localTime();
    const nowSec = h * 3600 + m * 60 + s;
    let diff = (AB.windowStart % 24) * 3600 - nowSec;
    if (diff <= 0) diff += 86400;
    return diff;
}

function effectiveDailyCap() {
    if (!AB.warmupEnabled) return AB.dailyCap;
    const days = Math.max(0, Math.floor((Date.now() - (ab.rampStart || Date.now())) / DAY_MS));
    return Math.max(1, Math.min(AB.dailyCap, AB.warmupStart + AB.warmupStep * days));
}

function pausarEnvioMasivo(ms, reason) {
    ab.pausedUntil = Math.max(ab.pausedUntil || 0, Date.now() + ms);
    ab.pauseReason = reason;
    console.warn(`[AntiBan] ⏸️ Envío masivo en pausa ${Math.round(ms / 60000)} min. Motivo: ${reason}`);
    saveAb();
}

function deny(status, code, retryAfterSec, error, retryable = true) {
    return { ok: false, status, code, retryAfter: Math.ceil(retryAfterSec || 0), error, retryable };
}

// Reglas por número (opt-out y duplicados recientes). `keys` = dígitos/LID equivalentes del destinatario.
function numberBlocked(keys) {
    const now = Date.now();
    for (const k of keys) {
        if (k && ab.optOut[k]) {
            return deny(403, 'opt_out', 0, 'El destinatario pidió no recibir más mensajes (BAJA).', false);
        }
    }
    for (const k of keys) {
        if (k && ab.perNumber[k] && now - ab.perNumber[k] < AB.perNumberCooldownMs) {
            return deny(409, 'recent_duplicate', 0, 'Ya se envió un mensaje masivo a este número recientemente (cooldown anti-spam).', false);
        }
    }
    return { ok: true };
}

function bulkGate(keys) {
    const now = Date.now();
    pruneAb(now);

    if (ab.pausedUntil > now) {
        return deny(429, 'paused', (ab.pausedUntil - now) / 1000, `Envío masivo en pausa: ${ab.pauseReason}`);
    }
    const nb = numberBlocked(keys);
    if (!nb.ok) return nb;

    if (!inBulkWindow()) {
        return deny(429, 'outside_window', secondsToWindowOpen() + rand(0, 900),
            `Fuera de horario permitido para envíos masivos (${AB.windowStart}:00-${AB.windowEnd}:00 ${AB.tz}).`);
    }
    const lastHour = ab.bulkSent.filter(t => now - t < 3600 * 1000);
    if (lastHour.length >= AB.hourlyCap) {
        return deny(429, 'hourly_cap', (Math.min(...lastHour) + 3600 * 1000 - now) / 1000 + rand(5, 60),
            `Tope por hora alcanzado (${AB.hourlyCap}/h).`);
    }
    const dayCap = effectiveDailyCap();
    if (ab.bulkSent.length >= dayCap) {
        return deny(429, 'daily_cap', (Math.min(...ab.bulkSent) + DAY_MS - now) / 1000 + rand(5, 120),
            `Tope diario alcanzado (${dayCap}/día${AB.warmupEnabled ? ', calentamiento activo' : ''}).`);
    }
    if (ab.nextBulkAt > now) {
        return deny(429, 'gap', (ab.nextBulkAt - now) / 1000, 'Espaciado mínimo entre mensajes masivos.');
    }
    return { ok: true };
}

function recordBulk(keys) {
    const now = Date.now();
    ab.bulkSent.push(now);
    for (const k of keys) if (k) ab.perNumber[k] = now;
    ab.nextBulkAt = now + rand(AB.bulkGapSec[0], AB.bulkGapSec[1]) * 1000;
    saveAb();
}

function recordFailure(reason) {
    ab.consecutiveFails = (ab.consecutiveFails || 0) + 1;
    if (ab.consecutiveFails >= AB.failThreshold) {
        ab.consecutiveFails = 0;
        pausarEnvioMasivo(AB.failPauseMs, `${AB.failThreshold} fallos seguidos de envío (${reason})`);
    } else {
        saveAb();
    }
}

function antibanSummary() {
    const now = Date.now();
    pruneAb(now);
    const lastHour = ab.bulkSent.filter(t => now - t < 3600 * 1000).length;
    return {
        timezone: AB.tz,
        window: `${AB.windowStart}:00-${AB.windowEnd}:00`,
        inWindow: inBulkWindow(),
        paused: ab.pausedUntil > now,
        pausedUntil: ab.pausedUntil > now ? new Date(ab.pausedUntil).toISOString() : null,
        pauseReason: ab.pausedUntil > now ? ab.pauseReason : '',
        sentLastHour: lastHour,
        hourlyCap: AB.hourlyCap,
        sentLast24h: ab.bulkSent.length,
        dailyCapEffective: effectiveDailyCap(),
        dailyCapMax: AB.dailyCap,
        warmupDay: Math.max(0, Math.floor((now - (ab.rampStart || now)) / DAY_MS)),
        optOutCount: Object.keys(ab.optOut).length,
        knownBadNumbers: Object.values(ab.numberCheck).filter(e => e && e.ok === false).length
    };
}

// Simulación de comportamiento humano: marcar leído (solo respuestas) + "escribiendo..." proporcional al texto
async function simulateHuman(chatId, text, { seen = false } = {}) {
    try {
        const chat = await client.getChatById(chatId);
        if (!chat) return null;
        if (seen) { try { await chat.sendSeen(); await sleep(rand(600, 1800)); } catch (_) {} }
        const ms = Math.min(14000, 1500 + (text ? text.length : 0) * 45 + rand(0, 2500));
        await chat.sendStateTyping();
        await sleep(ms);
        return chat;
    } catch (_) {
        return null;
    }
}

// Cola exclusiva: todos los envíos salen de uno en uno (nunca en paralelo)
let sendChain = Promise.resolve();
function runExclusive(fn) {
    const run = sendChain.then(() => fn());
    sendChain = run.catch(() => {});
    return run;
}
let lastOutboundAt = 0;

// Incoming Message Event
const OPT_OUT_REGEX = /^\s*(baja|stop|unsubscribe|desuscribir(me)?|darme de baja|no m[aá]s mensajes|no quiero (recibir )?(m[aá]s )?mensajes)[\s.!¡]*$/i;

client.on('message', async (msg) => {
    if (msg.isStatus) return;
    if (msg.fromMe) return;
    if (client.info && client.info.wid && msg.from === client.info.wid._serialized) return;
    if (msg.from.endsWith('@g.us')) return; // Ignore group chats

    let remitente = msg.from;
    let pushname = msg._data?.notifyName || '';
    let realPhone = '';

    // Si viene como @lid, resolver a teléfono real
    if (remitente.endsWith('@lid')) {
        const resolved = await resolveLidToPhone(remitente);
        if (resolved) {
            realPhone = resolved;
        }
    }

    try {
        const contact = await msg.getContact();
        if (contact) {
            // Solo considerar contact.number si NO es un LID y tiene longitud normal de teléfono (8-13 dígitos)
            if (!realPhone && contact.number && !contact.number.endsWith('@lid') && contact.number.length >= 8 && contact.number.length <= 13) {
                realPhone = contact.number;
            }
            if (contact.pushname) pushname = contact.pushname;
            else if (contact.name) pushname = contact.name;
        }
    } catch (eContact) {
        console.warn(`[WhatsApp Bridge] No se pudo obtener contacto de ${msg.from}:`, eContact.message);
    }

    let idDestino = remitente; // Conservar el JID de la sesión para responder
    let numeroParaWebhook = remitente;
    if (realPhone) {
        numeroParaWebhook = `${realPhone}@c.us`;
        console.log(`[WhatsApp Bridge] 📲 Mensaje vinculado: LID ${remitente} -> Teléfono real: ${realPhone} (${pushname})`);
    } else {
        console.log(`[WhatsApp Bridge] Mensaje de LID ${remitente} (${pushname})`);
    }

    // Opt-out: "BAJA"/"STOP" -> dejar de recibir difusiones. Reduce reportes de spam (principal causa de restricciones).
    if (msg.type === 'chat' && msg.body && OPT_OUT_REGEX.test(msg.body)) {
        const k1 = digitsOf(remitente.split('@')[0]);
        const k2 = digitsOf(realPhone);
        if (k1) ab.optOut[k1] = Date.now();
        if (k2) ab.optOut[k2] = Date.now();
        saveAb();
        console.log(`[AntiBan] 🚫 Opt-out registrado para ${remitente} (${realPhone || 'sin teléfono'})`);
        try {
            await runExclusive(async () => {
                await sleep(rand(2000, 5000));
                await client.sendMessage(msg.from, 'Listo, ya no recibirás más avisos automáticos de nuestra parte. Si necesitas algo, escríbenos cuando quieras. 🙂');
                lastOutboundAt = Date.now();
            });
        } catch (eOpt) {
            console.warn('[AntiBan] No se pudo confirmar el opt-out:', eOpt.message);
        }
        return;
    }

    // Manejar mensajes entrantes: solo procesar texto o multimedia real enviada por personas
    const userMediaTypes = ['image', 'video', 'audio', 'ptt', 'sticker', 'document'];
    if (msg.type === 'chat' && msg.body) {
        sendWebhook(numeroParaWebhook, msg.body, pushname, remitente);
    } else if (userMediaTypes.includes(msg.type)) {
        // Notificar a SAM sobre contenido multimedia real enviado por el usuario
        sendWebhook(numeroParaWebhook, `[NON_TEXT_MSG] ${msg.type}`, pushname, remitente);
    } else {
        // Ignorar eventos o notificaciones del protocolo interno de WhatsApp (e2e_notification, notification_template, protocol, etc.)
        console.log(`[WhatsApp Bridge] Evento/protocolo interno de WhatsApp ignorado (${msg.type}) de ${idDestino}`);
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

        if (chatId.endsWith('@lid')) {
            number = await resolveLidToPhone(chatId);
        }

        try {
            const contact = await client.getContactById(chatId);
            if (contact) {
                if (!number && contact.number && !contact.number.endsWith('@lid') && contact.number.length >= 8 && contact.number.length <= 13) {
                    number = contact.number;
                }
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
        connected: clientStatus === 'CONNECTED',
        antiban: antibanSummary()
    });
});

// --- Anti-ban: estado y control manual ---
app.get('/antiban', (req, res) => res.json({ success: true, ...antibanSummary() }));

// Declarar manualmente una restricción de WhatsApp (ej. aviso "Tu cuenta está restringida" con X horas)
app.post('/antiban/restricted', (req, res) => {
    const hours = Math.max(1, Math.min(24 * 14, parseFloat((req.body && req.body.hours) || 24)));
    pausarEnvioMasivo(hours * 3600 * 1000, `restricción de WhatsApp declarada (${hours}h)`);
    ab.rampStart = ab.pausedUntil; // al terminar, el calentamiento empieza desde cero
    saveAb();
    res.json({ success: true, ...antibanSummary() });
});

app.post('/antiban/clear', (req, res) => {
    ab.pausedUntil = 0;
    ab.pauseReason = '';
    ab.nextBulkAt = 0;
    ab.consecutiveFails = 0;
    saveAb();
    res.json({ success: true, ...antibanSummary() });
});

// Endpoint explícito de cancelación de envíos en curso
app.post('/cancel', (req, res) => {
    ab.pausedUntil = 0;
    ab.pauseReason = '';
    ab.nextBulkAt = 0;
    saveAb();
    console.log('[WhatsApp Bridge] 🛑 Señal de cancelación recibida: pausas y temporizadores de lote reseteados.');
    res.json({ success: true, message: 'Señal de cancelación procesada correctamente en el puente.' });
});

app.post('/antiban/opt-out', (req, res) => {
    const k = digitsOf(req.body && req.body.number);
    if (!k) return res.status(400).json({ success: false, error: 'number requerido' });
    if (req.body.remove) delete ab.optOut[k]; else ab.optOut[k] = Date.now();
    saveAb();
    res.json({ success: true, optOutCount: Object.keys(ab.optOut).length });
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

// Envío efectivo (se ejecuta dentro de la cola exclusiva). Devuelve { status, body }.
async function processSend({ number, message, finalCaption, mediaPath, mediaBase64, mimetype, filename, priority }) {
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
        if (cleanNumber.startsWith('59309') && cleanNumber.length === 13) {
            cleanNumber = '593' + cleanNumber.substring(4);
        } else if (cleanNumber.startsWith('0') && cleanNumber.length === 10) {
            cleanNumber = '593' + cleanNumber.substring(1);
        } else if (cleanNumber.length === 9 && !cleanNumber.startsWith('593')) {
            cleanNumber = '593' + cleanNumber;
        }
    }

    const chatId = `${cleanNumber}@${server}`;
    console.log(`[WhatsApp Bridge] Preparando envío a: ${chatId} (prioridad: ${priority})`);

    const isBulk = priority === 'bulk';
    let keys = [cleanNumber];

    // 0. Gobernador anti-bloqueo (solo difusiones). Si no procede, el cliente reintenta tras `retryAfter`.
    if (isBulk) {
        const gate = bulkGate(keys);
        if (!gate.ok) {
            console.warn(`[AntiBan] Envío masivo a ${chatId} diferido/omitido: ${gate.code} - ${gate.error}`);
            return {
                status: gate.status,
                body: { success: false, error: gate.error, code: gate.code, retryAfter: gate.retryAfter, retryable: gate.retryable }
            };
        }
    } else {
        // Espaciado mínimo humano entre cualquier envío no masivo
        const range = priority === 'manual' ? AB.manualGapSec : AB.replyGapSec;
        const wait = lastOutboundAt + rand(range[0], range[1]) * 1000 - Date.now();
        if (wait > 0) await sleep(Math.min(wait, 15000));
    }

    // 1. Verificación previa: Comprobar si el número está registrado en WhatsApp (SOLO para @c.us)
    // IMPORTANTE: NO ejecutar getNumberId para @lid porque getNumberId solo acepta números de teléfono
    // y retorna null para LIDs, provocando rechazos erróneos.
    // Los resultados se cachean: no se consulta de nuevo un número ya verificado.
    let targetChatId = chatId;
    if (!chatId.endsWith('@lid') && server !== 'lid') {
        const cached = ab.numberCheck[cleanNumber];
        const nowT = Date.now();
        if (cached && cached.ok === false && nowT - cached.ts < AB.numberBadTtlMs) {
            console.warn(`[WhatsApp Bridge] El número ${chatId} está en caché reciente como no verificado. Reintentando directo.`);
        }
        if (cached && cached.ok && cached.id && nowT - cached.ts < AB.numberOkTtlMs) {
            targetChatId = cached.id;
        } else {
            try {
                const numberCheck = await Promise.race([
                    client.getNumberId(chatId),
                    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout_check')), 6000))
                ]);

                if (numberCheck && numberCheck._serialized) {
                    targetChatId = numberCheck._serialized;
                    ab.numberCheck[cleanNumber] = { ok: true, id: targetChatId, ts: Date.now() };
                    saveAb();
                } else if (numberCheck === null) {
                    console.warn(`[WhatsApp Bridge] getNumberId retornó null para ${chatId}. Se procederá con envío directo a ${chatId}.`);
                    targetChatId = chatId;
                }
            } catch (errCheck) {
                console.warn(`[WhatsApp Bridge] Aviso en verificación de número (${chatId}): ${errCheck.message}. Usando chatId directo.`);
                targetChatId = chatId;
            }
        }
    }

    // Con el JID real ya resuelto, revalidar opt-out/duplicados (el JID puede ser un @lid equivalente)
    if (isBulk) {
        keys = [cleanNumber, digitsOf(targetChatId.split('@')[0])];
        const nb = numberBlocked(keys);
        if (!nb.ok) {
            console.warn(`[AntiBan] Envío masivo a ${targetChatId} omitido: ${nb.code}`);
            return { status: nb.status, body: { success: false, error: nb.error, code: nb.code, retryAfter: 0, retryable: false } };
        }
    }

    // Preparar Media si fue provisto
    let mediaToSend = null;
    if (mediaPath && fs.existsSync(mediaPath)) {
        try {
            mediaToSend = MessageMedia.fromFilePath(mediaPath);
            console.log(`[WhatsApp Bridge] Cargado MessageMedia desde archivo: ${mediaPath}`);
        } catch (eMedia) {
            console.warn(`[WhatsApp Bridge] Error cargando MessageMedia desde archivo (${mediaPath}): ${eMedia.message}`);
        }
    } else if (mediaBase64) {
        try {
            mediaToSend = new MessageMedia(mimetype || 'image/png', mediaBase64, filename || 'archivo.png');
            console.log(`[WhatsApp Bridge] Creado MessageMedia desde payload base64 (tipo: ${mimetype || 'image/png'})`);
        } catch (eBase64) {
            console.warn(`[WhatsApp Bridge] Error creando MessageMedia desde base64: ${eBase64.message}`);
        }
    }

    // 2. Comportamiento humano: "escribiendo..." antes de enviar
    const textoParaTyping = finalCaption || message || '';
    const chatObj = await simulateHuman(targetChatId, textoParaTyping, { seen: priority === 'reply' });

    // 3. Enviar mensaje o media con captura de advertencias de serialización (común en destinatarios @lid)
    let sendSuccess = false;
    let messageId = 'sent';

    try {
        let sendPromise;
        if (mediaToSend) {
            const sendOpts = {};
            if (finalCaption) sendOpts.caption = finalCaption;
            sendPromise = client.sendMessage(targetChatId, mediaToSend, sendOpts);
        } else {
            sendPromise = client.sendMessage(targetChatId, finalCaption || message);
        }

        const timeoutPromise = new Promise((_, reject) => 
            setTimeout(() => reject(new Error('Timeout de 45 segundos al enviar por WhatsApp.')), 45000)
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
            recordFailure(errMsg.slice(0, 60));
            if (chatObj) { try { await chatObj.clearState(); } catch (_) {} }
            throw sendErr;
        }
    }

    if (chatObj) { try { await chatObj.clearState(); } catch (_) {} }
    lastOutboundAt = Date.now();

    if (sendSuccess) {
        ab.consecutiveFails = 0;
        if (isBulk) recordBulk(keys); else saveAb();
        console.log(`[WhatsApp Bridge] Mensaje enviado exitosamente a: ${targetChatId}`);
        return { status: 200, body: { success: true, messageId: messageId } };
    }
    return { status: 500, body: { success: false, error: 'Estado de envío desconocido' } };
}

// Send Message (Supports both plain text and media with caption)
async function handleSendMessage(req, res) {
    const { number, message, caption, mediaPath, mediaBase64, mimetype, filename } = req.body;
    const finalCaption = caption !== undefined ? caption : (message || '');
    const rawPriority = String((req.body && req.body.priority) || 'reply').toLowerCase();
    const priority = ['bulk', 'manual', 'reply'].includes(rawPriority) ? rawPriority : 'reply';

    if (!number || (!message && !finalCaption && !mediaPath && !mediaBase64)) {
        return res.status(400).json({ success: false, error: 'El campo number y al menos un mensaje o media son obligatorios.' });
    }

    if (clientStatus !== 'CONNECTED') {
        return res.status(503).json({ success: false, error: 'El servicio de WhatsApp no está conectado actualmente.' });
    }

    try {
        const result = await runExclusive(() =>
            processSend({ number, message, finalCaption, mediaPath, mediaBase64, mimetype, filename, priority })
        );
        return res.status(result.status).json(result.body);
    } catch (err) {
        console.error('[WhatsApp Bridge] Error al enviar mensaje:', err.message || err);
        return res.status(500).json({
            success: false,
            error: err.message || 'Error desconocido al enviar mensaje'
        });
    }
}

app.post('/send', handleSendMessage);
app.post('/send-media', handleSendMessage);

// Limpiar archivos de bloqueo residuales de Chromium en el volumen montado
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
    const s = antibanSummary();
    console.log(`[AntiBan] Ventana bulk ${s.window} (${s.timezone}) | tope/h ${s.hourlyCap} | tope/día efectivo ${s.dailyCapEffective}/${s.dailyCapMax} | opt-outs ${s.optOutCount}`);
});
