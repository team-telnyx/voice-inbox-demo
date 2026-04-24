"""
Voice Inbox — TeXML + Edge Compute + Telnyx Storage

A business voicemail system that demonstrates all three Telnyx products:
1. TeXML — Declarative call flow (IVR, recording, playback)
2. Edge Compute — Serverless, always-on, zero infrastructure
3. Telnyx Storage — S3-compatible persistence for voicemails & call logs

Caller flow:  Call in → greeting → leave voicemail → saved to Storage
Owner flow:    Call from owner number → admin menu → listen to messages
Dashboard:     Web UI at /dashboard showing voicemails, call logs, and live stats
"""
import logging
import json
import os
import hashlib
import hmac
import datetime
import urllib.parse
import urllib.request

# ── Config ──────────────────────────────────────────────────────────────────
HTTP_SCOPE_TYPE = 'http'

STORAGE_ENDPOINT = "https://us-central-1.telnyxcloudstorage.com"
STORAGE_REGION = "us-central-1"
STORAGE_BUCKET = os.getenv("TELNYX_STORAGE_BUCKET", "voice-inbox-demo")
STORAGE_PREFIX = "voice-inbox"

OWNER_NUMBER = os.getenv("OWNER_NUMBER", "+10000000000")  # Set this to the number that gets admin access
OWNER_SIP = os.getenv("OWNER_SIP", "")  # Optional: SIP URI for owner
BUSINESS_NAME = os.getenv("BUSINESS_NAME", "Acme Corp")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "+10000000000")  # Your Telnyx number


# ── AWS Sig V4 for Telnyx Storage ────────────────────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def s3_request(method: str, key: str, body: bytes = b'',
               content_type: str = 'application/json', api_key: str = '') -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')
    service = 's3'

    payload_hash = hashlib.sha256(body).hexdigest()
    host = f"{STORAGE_REGION}.telnyxcloudstorage.com"
    canonical_uri = f"/{STORAGE_BUCKET}/{key}"

    headers_to_sign = {
        'content-type': content_type,
        'host': host,
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': amz_date,
    }
    signed_headers_str = ';'.join(sorted(headers_to_sign.keys()))
    canonical_headers = ''
    for k in sorted(headers_to_sign.keys()):
        canonical_headers += f'{k}:{headers_to_sign[k]}\n'

    canonical_request = (
        f"{method}\n{canonical_uri}\n\n{canonical_headers}\n"
        f"{signed_headers_str}\n{payload_hash}"
    )

    credential_scope = f"{date_stamp}/{STORAGE_REGION}/{service}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )

    signing_key = _sign(_sign(_sign(_sign(('AWS4' + api_key).encode(), date_stamp), STORAGE_REGION), service), 'aws4_request')
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    auth_header = (
        f"AWS4-HMAC-SHA256 Credential={api_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )

    url = f"{STORAGE_ENDPOINT}/{STORAGE_BUCKET}/{key}"
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': content_type,
        'Host': host,
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': amz_date,
        'Authorization': auth_header,
    }, method=method)

    try:
        resp = urllib.request.urlopen(req)
        return {"status": resp.status, "body": resp.read().decode() if resp.status != 204 else ""}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "body": e.read().decode() if e.code != 404 else ""}
    except Exception as e:
        return {"status": 0, "body": str(e)}


def s3_list(prefix: str, api_key: str) -> list:
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')
    service = 's3'
    host = f"{STORAGE_REGION}.telnyxcloudstorage.com"

    query_string = f"list-type=2&prefix={urllib.parse.quote(prefix)}&max-keys=100"
    canonical_uri = f"/{STORAGE_BUCKET}"

    payload_hash = hashlib.sha256(b'').hexdigest()
    headers_to_sign = {
        'host': host,
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': amz_date,
    }
    signed_headers_str = ';'.join(sorted(headers_to_sign.keys()))
    canonical_headers = ''
    for k in sorted(headers_to_sign.keys()):
        canonical_headers += f'{k}:{headers_to_sign[k]}\n'

    canonical_request = (
        f"GET\n{canonical_uri}\n{query_string}\n{canonical_headers}\n"
        f"{signed_headers_str}\n{payload_hash}"
    )

    credential_scope = f"{date_stamp}/{STORAGE_REGION}/{service}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )

    signing_key = _sign(_sign(_sign(_sign(('AWS4' + api_key).encode(), date_stamp), STORAGE_REGION), service), 'aws4_request')
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()

    auth_header = (
        f"AWS4-HMAC-SHA256 Credential={api_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )

    url = f"{STORAGE_ENDPOINT}/{STORAGE_BUCKET}?{query_string}"
    req = urllib.request.Request(url, headers={
        'Host': host,
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': amz_date,
        'Authorization': auth_header,
    })

    try:
        resp = urllib.request.urlopen(req)
        body = resp.read().decode()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(body)
        ns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
        objects = []
        for content in root.findall('.//s3:Contents/s3:Key', ns):
            objects.append(content.text if hasattr(content, 'text') else str(content))
        if not objects:
            for content in root.iter('Key'):
                objects.append(content.text or '')
        return objects
    except Exception as e:
        logging.error(f"S3 list error: {e}")
        return []


# ── Storage helpers ──────────────────────────────────────────────────────────

def store_voicemail_meta(call_sid: str, from_number: str, recording_url: str,
                         duration: str, api_key: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime('%Y%m%d%H%M%S')
    date_str = now.strftime('%Y-%m-%d')

    meta = {
        "call_sid": call_sid,
        "from": from_number,
        "recording_url": recording_url,
        "duration_seconds": duration,
        "timestamp": now.isoformat(),
        "date": date_str,
    }

    key = f"{STORAGE_PREFIX}/messages/{date_str}/{call_sid}_{timestamp}.json"
    body = json.dumps(meta, indent=2).encode()
    result = s3_request('PUT', key, body, 'application/json', api_key)
    logging.info(f"Stored voicemail meta: {key} -> {result['status']}")
    return key


def store_call_log(call_sid: str, event: str, data: dict, api_key: str):
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.strftime('%Y%m%d%H%M%S')
    date_str = now.strftime('%Y-%m-%d')

    log = {
        "call_sid": call_sid,
        "event": event,
        "timestamp": now.isoformat(),
        "data": data,
    }

    key = f"{STORAGE_PREFIX}/logs/{date_str}/{call_sid}_{event}_{timestamp}.json"
    body = json.dumps(log, indent=2).encode()
    result = s3_request('PUT', key, body, 'application/json', api_key)
    logging.info(f"Stored call log: {key} -> {result['status']}")


def count_voicemails(api_key: str) -> int:
    keys = s3_list(f"{STORAGE_PREFIX}/messages/", api_key)
    return len([k for k in keys if k.endswith('.json')])


def get_all_voicemails(api_key: str) -> list:
    """Get all voicemail metadata, newest first."""
    keys = s3_list(f"{STORAGE_PREFIX}/messages/", api_key)
    voicemails = []
    for k in sorted(keys, reverse=True):
        if k.endswith('.json'):
            result = s3_request('GET', k, api_key=api_key)
            if result['status'] == 200 and result['body']:
                try:
                    meta = json.loads(result['body'])
                    meta['storage_key'] = k
                    voicemails.append(meta)
                except:
                    pass
    return voicemails


def get_all_call_logs(api_key: str) -> list:
    """Get all call logs, newest first."""
    keys = s3_list(f"{STORAGE_PREFIX}/logs/", api_key)
    logs = []
    for k in sorted(keys, reverse=True):
        if k.endswith('.json'):
            result = s3_request('GET', k, api_key=api_key)
            if result['status'] == 200 and result['body']:
                try:
                    log = json.loads(result['body'])
                    log['storage_key'] = k
                    logs.append(log)
                except:
                    pass
    return logs


def get_latest_voicemail(api_key: str) -> dict:
    keys = s3_list(f"{STORAGE_PREFIX}/messages/", api_key)
    if not keys:
        return {}
    latest_key = sorted(keys)[-1]
    result = s3_request('GET', latest_key, api_key=api_key)
    if result['status'] == 200 and result['body']:
        try:
            return json.loads(result['body'])
        except:
            return {}
    return {}


# ── Dashboard HTML ───────────────────────────────────────────────────────────

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Voice Inbox</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#08080d;--surface:#111118;--card:#16161f;--border:#222235;--accent:#7c6cf0;--accent2:#b0a4ff;--green:#00d49b;--red:#ff6b55;--text:#eaeaf2;--muted:#7777a0;--font:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
body{font-family:var(--font);background:var(--bg);color:var(--text);min-height:100vh}

/* Layout */
.container{max-width:960px;margin:0 auto;padding:2rem}
.top-bar{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem}
.top-bar h1{font-size:1.4rem;font-weight:800;display:flex;align-items:center;gap:0.5rem}
.top-bar h1 span{background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.refresh-btn{background:var(--surface);border:1px solid var(--border);color:var(--text);padding:0.4rem 1rem;border-radius:0.5rem;cursor:pointer;font-size:0.8rem;font-weight:600;transition:all 0.15s}
.refresh-btn:hover{border-color:var(--accent);color:var(--accent2)}

/* Hero — phone number + products */
.hero{background:var(--surface);border:1px solid var(--border);border-radius:1rem;padding:2rem;text-align:center;margin-bottom:2rem}
.hero h2{font-size:2.2rem;font-weight:800;margin-bottom:0.25rem}
.hero h2 a{color:var(--accent2);text-decoration:none}
.hero h2 a:hover{text-decoration:underline}
.hero .subtitle{color:var(--muted);font-size:0.9rem;margin-bottom:1.5rem}
.products{display:flex;justify-content:center;gap:1.5rem;flex-wrap:wrap}
.product{background:var(--card);border:1px solid var(--border);border-radius:0.75rem;padding:0.75rem 1.25rem;text-align:center;min-width:140px}
.product .name{font-weight:700;font-size:0.9rem}
.product .desc{color:var(--muted);font-size:0.75rem;margin-top:0.1rem}
.product .st{margin-top:0.4rem}

/* Stats row */
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;margin-bottom:2rem}
.stat-card{background:var(--surface);border:1px solid var(--border);border-radius:1rem;padding:1.5rem;text-align:center}
.stat-card .value{font-size:2.5rem;font-weight:800;color:var(--accent2);line-height:1}
.stat-card .label{color:var(--muted);font-size:0.75rem;margin-top:0.4rem;text-transform:uppercase;letter-spacing:0.08em;font-weight:600}

/* Sections */
.section{margin-bottom:2rem}
.section-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:0.75rem}
.section-head h2{font-size:1.1rem;font-weight:700;display:flex;align-items:center;gap:0.4rem}
.auto-refresh{color:var(--muted);font-size:0.7rem}

/* Voicemails */
.voicemail-list{display:flex;flex-direction:column;gap:0.5rem}
.voicemail{background:var(--surface);border:1px solid var(--border);border-radius:0.75rem;padding:1rem 1.25rem;display:flex;align-items:center;gap:1rem;transition:border-color 0.15s}
.voicemail:hover{border-color:var(--accent)}
.voicemail .icon{font-size:1.8rem;flex-shrink:0}
.voicemail .info{flex:1;min-width:0}
.voicemail .from{font-weight:600;font-size:0.95rem}
.voicemail .meta{color:var(--muted);font-size:0.8rem;margin-top:0.15rem}
.voicemail .dur{background:var(--accent);color:white;padding:0.25rem 0.75rem;border-radius:1rem;font-size:0.8rem;font-weight:700;white-space:nowrap;flex-shrink:0}
.voicemail-player{width:100%;margin-top:0.5rem;height:36px;border-radius:0.5rem}
.play-btn{background:var(--accent);color:white;border:none;padding:0.35rem 0.9rem;border-radius:0.5rem;cursor:pointer;font-size:0.8rem;font-weight:700;transition:all 0.15s;flex-shrink:0}
.play-btn:hover{opacity:0.85}
.play-btn.playing{background:var(--red)}

/* Call logs */
.log-list{display:flex;flex-direction:column;gap:0.4rem}
.log-entry{background:var(--surface);border:1px solid var(--border);border-radius:0.5rem;padding:0.65rem 1rem;font-size:0.85rem}
.log-top{display:flex;align-items:center;gap:0.75rem}
.log-entry .ev{font-weight:600}
.log-entry .detail{color:var(--muted);font-size:0.8rem}
.log-entry .time{color:var(--muted);font-size:0.75rem;margin-left:auto;white-space:nowrap}

/* Badges */
.badge{display:inline-block;padding:0.2rem 0.55rem;border-radius:0.35rem;font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.03em}
.badge-green{background:#00d49b18;color:var(--green)}
.badge-red{background:#ff6b5518;color:var(--red)}
.badge-purple{background:#7c6cf018;color:var(--accent)}

/* Empty state */
.empty-state{text-align:center;padding:3rem 1rem;color:var(--muted)}
.empty-state .icon{font-size:3rem;margin-bottom:0.75rem}
.empty-state p{font-size:0.9rem;line-height:1.5}

/* Responsive */
@media(max-width:640px){
.container{padding:1rem}
.hero h2{font-size:1.6rem}
.stats{grid-template-columns:repeat(3,1fr);gap:0.5rem}
.stat-card{padding:1rem 0.5rem}
.stat-card .value{font-size:1.8rem}
.products{gap:0.5rem}
.product{min-width:0;padding:0.5rem 0.75rem}
}
</style>
</head>
<body>
<div class="container">

<div class="top-bar">
    <h1>📱 <span>Voice Inbox</span></h1>
    <button class="refresh-btn" onclick="loadData()">🔄 Refresh</button>
</div>

<div class="hero">
    <h2 id="phone-display"><a href="#" id="phone-link">Loading...</a></h2>
    <div class="subtitle">Business Voicemail — TeXML + Edge Compute + Telnyx Storage</div>
    <div class="products">
        <div class="product">
            <div class="name">🎙️ TeXML</div>
            <div class="desc">IVR &amp; Recording</div>
            <div class="st"><span class="badge badge-green">Live</span></div>
        </div>
        <div class="product">
            <div class="name">⚡ Edge Compute</div>
            <div class="desc">Serverless</div>
            <div class="st"><span class="badge badge-green">Running</span></div>
        </div>
        <div class="product">
            <div class="name">💾 Storage</div>
            <div class="desc">S3-Compatible</div>
            <div class="st"><span class="badge badge-green" id="storage-badge">OK</span></div>
        </div>
    </div>
</div>

<div class="stats" id="stats"></div>

<div class="section">
    <div class="section-head">
        <h2>📩 Voicemails</h2>
        <span class="auto-refresh" id="auto-refresh"></span>
    </div>
    <div class="voicemail-list" id="voicemails"></div>
</div>

<div class="section">
    <div class="section-head">
        <h2>📋 Call Activity</h2>
    </div>
    <div class="log-list" id="call-logs"></div>
</div>

</div>

<script>
let refreshInterval;
let phoneNumber = '';

async function loadData() {
    try {
        const [voicemails, logs, health, config] = await Promise.all([
            fetch('/api/voicemails').then(r => r.json()),
            fetch('/api/logs').then(r => r.json()),
            fetch('/health').then(r => r.json()),
            fetch('/api/config').then(r => r.json()).catch(() => ({}))
        ]);

        // Update phone display
        if (config.phone_number) {
            phoneNumber = config.phone_number;
            const fmt = phoneNumber.replace(/^\+(\d)(\d{3})(\d{3})(\d{4})$/, '+$1 ($2) $3-$4');
            document.getElementById('phone-link').textContent = fmt;
            document.getElementById('phone-link').href = 'tel:' + phoneNumber;
        }

        // Stats
        const vmCount = voicemails.length;
        const callCount = logs.filter(l => l.event === 'call_initiated').length;
        const logCount = logs.length;
        document.getElementById('stats').innerHTML = `
            <div class="stat-card"><div class="value">${vmCount}</div><div class="label">Voicemails</div></div>
            <div class="stat-card"><div class="value">${callCount}</div><div class="label">Total Calls</div></div>
            <div class="stat-card"><div class="value">${logCount}</div><div class="label">Events</div></div>
        `;

        // Storage badge
        const sb = document.getElementById('storage-badge');
        sb.textContent = health.storage?.status === 'connected' ? 'Connected' : 'Error';
        sb.className = 'badge ' + (health.storage?.status === 'connected' ? 'badge-green' : 'badge-red');

        // Voicemails
        const vmDiv = document.getElementById('voicemails');
        if (voicemails.length === 0) {
            vmDiv.innerHTML = '<div class="empty-state"><div class="icon">📭</div><p>No voicemails yet. Call your Telnyx number to leave one!</p></div>';
        } else {
            vmDiv.innerHTML = voicemails.map((vm, i) => {
                const ts = new Date(vm.timestamp).toLocaleString();
                const from = vm.from || 'Unknown';
                const dur = vm.duration_seconds || '?';
                const audioId = 'audio-' + i;
                return `<div class="voicemail">
                    <div class="icon">🎙️</div>
                    <div class="info">
                        <div class="from">${from}</div>
                        <div class="meta">${ts} · ${dur}s</div>
                    </div>
                    <button class="play-btn" onclick="togglePlay('${audioId}', this)">▶ Play</button>
                    <audio id="${audioId}" src="/api/recording/${encodeURIComponent(vm.call_sid)}" preload="none"></audio>
                </div>`;
            }).join('');
        }

        // Call logs
        const logDiv = document.getElementById('call-logs');
        if (logs.length === 0) {
            logDiv.innerHTML = '<div class="empty-state"><div class="icon">📋</div><p>No call activity yet.</p></div>';
        } else {
            logDiv.innerHTML = logs.slice(0, 20).map(log => {
                const ts = new Date(log.timestamp).toLocaleString();
                const ev = log.event || 'unknown';
                const evBadge = ev.includes('voicemail') ? 'badge-purple' : ev.includes('initiated') ? 'badge-green' : 'badge';
                const detail = log.data?.from ? 'from ' + log.data.from : '';
                return `<div class="log-entry">
                    <div class="log-top">
                        <span class="ev"><span class="badge ${evBadge}">${ev}</span></span>
                        ${detail ? '<span class="detail">' + detail + '</span>' : ''}
                        <span class="time">${ts}</span>
                    </div>
                </div>`;
            }).join('');
        }

        document.getElementById('auto-refresh').textContent = 'Auto-refresh 10s';
    } catch (e) {
        console.error('Load error:', e);
    }
}

loadData();
refreshInterval = setInterval(loadData, 10000);

function togglePlay(audioId, btn) {
    const audio = document.getElementById(audioId);
    if (!audio) return;
    if (audio.paused) {
        document.querySelectorAll('audio').forEach(a => { if (a.id !== audioId) { a.pause(); a.currentTime = 0; } });
        document.querySelectorAll('.play-btn').forEach(b => { if (b !== btn) { b.textContent = '▶ Play'; b.classList.remove('playing'); } });
        audio.play();
        btn.textContent = '⏹ Stop';
        btn.classList.add('playing');
        audio.onended = () => { btn.textContent = '▶ Play'; btn.classList.remove('playing'); };
    } else {
        audio.pause();
        audio.currentTime = 0;
        btn.textContent = '▶ Play';
        btn.classList.remove('playing');
    }
}
</script>
</body>
</html>'''


# ── Edge Compute Function ────────────────────────────────────────────────────

def get_fresh_recording_url(call_sid: str, api_key: str) -> str:
    """Get a fresh presigned recording URL from Telnyx Recordings API."""
    try:
        api_url = f"https://api.telnyx.com/v2/recordings?filter[call_control_id]={urllib.parse.quote(call_sid, safe='')}"
        req = urllib.request.Request(api_url)
        req.add_header('Authorization', f'Bearer {api_key}')
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        recordings = data.get('data', [])
        if recordings:
            return recordings[0].get('download_urls', {}).get('mp3', '')
    except Exception as e:
        logging.error(f"Fresh recording URL error: {e}")
    return ''


def new():
    return Function()


class Function:
    def __init__(self):
        self.telnyx_api_key = None

    def start(self, cfg):
        logging.info("Voice Inbox starting")
        env_key = os.getenv("TELNYX_API_KEY", "")
        cfg_key = cfg.get("TELNYX_API_KEY", "")
        if env_key and (env_key.startswith("KEY") and len(env_key) <= 70):
            self.telnyx_api_key = env_key
        elif cfg_key and (cfg_key.startswith("KEY") and len(cfg_key) <= 70):
            self.telnyx_api_key = cfg_key
        elif os.getenv("REALAPIKEY", "").startswith("KEY"):
            self.telnyx_api_key = os.getenv("REALAPIKEY")
        else:
            self.telnyx_api_key = env_key or cfg_key
        logging.info(f"API key resolved: prefix={self.telnyx_api_key[:6]}... len={len(self.telnyx_api_key)}")

    def stop(self):
        logging.info("Voice Inbox stopping")

    async def handle(self, scope, receive, send):
        if scope.get('type') != HTTP_SCOPE_TYPE:
            await self._send_error(send, 400, "Bad Request")
            return

        path = scope.get('path', '/')
        method = scope.get('method', 'GET')

        body = {}
        if method == 'POST':
            body = await self._read_body(receive)

        logging.info(f"{method} {path}")

        # ── Routes ──
        # TeXML call flows
        if path == '/voice' and method == 'POST':
            await self._handle_voice(body, send)
        elif path == '/menu' and method == 'POST':
            await self._handle_menu(body, send)
        elif path == '/recording-complete' and method == 'POST':
            await self._handle_recording_complete(body, send)
        elif path == '/recording-status' and method == 'POST':
            await self._send_json(send, {"status": "ok"})
        elif path == '/status' and method == 'POST':
            await self._handle_status(body, send)
        # Dashboard & API
        elif path == '/dashboard' and method == 'GET':
            await self._send_html(send, DASHBOARD_HTML)
        elif path == '/api/voicemails' and method == 'GET':
            await self._handle_api_voicemails(send)
        elif path == '/api/logs' and method == 'GET':
            await self._handle_api_logs(send)
        elif path == '/api/stats' and method == 'GET':
            await self._handle_api_stats(send)
        elif path.startswith('/api/recording/') and method == 'GET':
            await self._handle_api_recording(path, send)
        elif path == '/api/config' and method == 'GET':
            await self._send_json(send, {
                "business_name": BUSINESS_NAME,
                "phone_number": PHONE_NUMBER,
                "storage_bucket": STORAGE_BUCKET,
                "storage_region": STORAGE_REGION,
            })
        elif path == '/debug/storage' and method == 'GET':
            await self._handle_debug_storage(send)
        elif path == '/health' or path == '/':
            await self._handle_health(send)
        else:
            await self._send_error(send, 404, "Not Found")

    # ── Request helpers ──────────────────────────────────────────────────

    async def _read_body(self, receive):
        body_bytes = b''
        while True:
            message = await receive()
            if message['type'] == 'http.request':
                body_bytes += message.get('body', b'')
                if not message.get('more_body', False):
                    break
        if not body_bytes:
            return {}
        try:
            return json.loads(body_bytes.decode('utf-8'))
        except json.JSONDecodeError:
            try:
                return dict(urllib.parse.parse_qsl(body_bytes.decode('utf-8')))
            except:
                return {}

    async def _send_texml(self, send, texml_body: str):
        response = f'<?xml version="1.0" encoding="UTF-8"?>\n<Response>\n{texml_body}\n</Response>'
        await send({'type': 'http.response.start', 'status': 200,
                    'headers': [[b'content-type', b'application/xml']]})
        await send({'type': 'http.response.body', 'body': response.encode()})

    async def _send_json(self, send, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [[b'content-type', b'application/json'],
                                [b'access-control-allow-origin', b'*']]})
        await send({'type': 'http.response.body', 'body': body})

    async def _send_html(self, send, html: str, status: int = 200):
        body = html.encode()
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [[b'content-type', b'text/html; charset=utf-8']]})
        await send({'type': 'http.response.body', 'body': body})

    async def _send_error(self, send, status: int, message: str):
        await self._send_json(send, {"error": message}, status)

    # ── API endpoints ────────────────────────────────────────────────────

    async def _handle_api_voicemails(self, send):
        """Return all voicemails as JSON."""
        try:
            voicemails = get_all_voicemails(self.telnyx_api_key)
            await self._send_json(send, voicemails)
        except Exception as e:
            logging.error(f"API voicemails error: {e}")
            await self._send_json(send, [])

    async def _handle_api_logs(self, send):
        """Return all call logs as JSON."""
        try:
            logs = get_all_call_logs(self.telnyx_api_key)
            await self._send_json(send, logs)
        except Exception as e:
            logging.error(f"API logs error: {e}")
            await self._send_json(send, [])

    async def _handle_api_stats(self, send):
        """Return stats as JSON."""
        try:
            vm_count = count_voicemails(self.telnyx_api_key)
            logs = get_all_call_logs(self.telnyx_api_key)
            call_count = len([l for l in logs if l.get('event') == 'call_initiated'])
            await self._send_json(send, {
                "voicemail_count": vm_count,
                "total_calls": call_count,
                "total_events": len(logs),
            })
        except Exception as e:
            logging.error(f"API stats error: {e}")
            await self._send_json(send, {"error": str(e)})

    async def _handle_api_recording(self, path, send):
        """Proxy recording audio — fetches fresh URL from Telnyx API."""
        try:
            call_sid = path.split('/api/recording/')[-1]
            call_sid = urllib.parse.unquote(call_sid)
            download_url = get_fresh_recording_url(call_sid, self.telnyx_api_key)
            if not download_url:
                await self._send_error(send, 404, 'Recording not found')
                return
            audio_resp = urllib.request.urlopen(download_url, timeout=15)
            audio_data = audio_resp.read()
            content_type = audio_resp.headers.get('Content-Type', 'audio/mpeg')
            await send({'type': 'http.response.start', 'status': 200,
                        'headers': [[b'content-type', content_type.encode()],
                                     [b'access-control-allow-origin', b'*'],
                                     [b'cache-control', b'no-cache']]})
            await send({'type': 'http.response.body', 'body': audio_data})
        except Exception as e:
            logging.error(f"Recording proxy error: {e}")
            await self._send_error(send, 500, f'Recording fetch failed: {e}')

    # ── Call handlers ────────────────────────────────────────────────────

    async def _handle_voice(self, body, send):
        call_sid = body.get("CallSid", "unknown")
        from_number = body.get("From", "unknown")
        to_number = body.get("To", "unknown")

        logging.info(f"📞 Call from {from_number} to {to_number}")

        store_call_log(call_sid, "call_initiated",
                       {"from": from_number, "to": to_number},
                       self.telnyx_api_key)

        is_owner = (from_number.endswith(OWNER_NUMBER.lstrip('+')) or
                    from_number == OWNER_NUMBER or
                    OWNER_NUMBER in from_number or
                    from_number == OWNER_SIP or
                    OWNER_SIP in from_number)

        if is_owner:
            try:
                msg_count = count_voicemails(self.telnyx_api_key)
            except:
                msg_count = 0

            count_text = "no messages" if msg_count == 0 else \
                         f"{msg_count} message{'s' if msg_count != 1 else ''}"

            texml = f"""
    <Say voice="Polly.Joanna">
        Welcome back. You have {count_text} in your voice inbox.
    </Say>
    <Gather input="dtmf" numDigits="1" action="/menu" method="POST" timeout="10">
        <Say voice="Polly.Joanna">
            Press 1 to hear your latest message.
            Press 2 to hear your message count and call stats.
            Press 3 to leave a voicemail yourself.
            Press 0 to hang up.
        </Say>
    </Gather>
    <Say voice="Polly.Joanna">Goodbye.</Say>
    <Hangup/>"""
        else:
            texml = f"""
    <Say voice="Polly.Joanna">
        Hello, you've reached {BUSINESS_NAME}. 
        We can't take your call right now, but please leave a message after the beep.
    </Say>
    <Record 
        action="/recording-complete" 
        method="POST"
        maxLength="30"
        timeout="5"
        finishOnKey="#"
        playBeep="true"
        recordingStatusCallback="/recording-status"
        recordingStatusCallbackMethod="POST"
    />
    <Say voice="Polly.Joanna">
        Thank you for your message. We will get back to you soon. Goodbye.
    </Say>
    <Hangup/>"""

        await self._send_texml(send, texml)

    async def _handle_menu(self, body, send):
        call_sid = body.get("CallSid", "unknown")
        digits = body.get("Digits", "")

        logging.info(f"🔢 Owner pressed {digits}")

        store_call_log(call_sid, "menu_selection", {"digits": digits},
                       self.telnyx_api_key)

        if digits == "1":
            try:
                voicemail = get_latest_voicemail(self.telnyx_api_key)
                if voicemail:
                    duration = voicemail.get("duration_seconds", "?")
                    from_num = voicemail.get("from", "unknown")
                    recording_url = get_fresh_recording_url(voicemail["call_sid"], self.telnyx_api_key)
                    if recording_url:
                        texml = f"""
    <Say voice="Polly.Joanna">
        Latest message from {self._speak_number(from_num)}, {duration} seconds long.
    </Say>
    <Play>{recording_url}</Play>
    <Say voice="Polly.Joanna">End of message.</Say>
    <Redirect>/voice</Redirect>"""
                    else:
                        texml = """
    <Say voice="Polly.Joanna">
        Recording is no longer available.
    </Say>
    <Redirect>/voice</Redirect>"""
                else:
                    texml = """
    <Say voice="Polly.Joanna">
        No messages found. Your voice inbox is empty.
    </Say>
    <Redirect>/voice</Redirect>"""
            except Exception as e:
                logging.error(f"Storage read error: {e}")
                texml = """
    <Say voice="Polly.Joanna">
        Sorry, there was an error reading from storage.
    </Say>
    <Redirect>/voice</Redirect>"""

        elif digits == "2":
            try:
                msg_count = count_voicemails(self.telnyx_api_key)
            except:
                msg_count = -1

            if msg_count >= 0:
                texml = f"""
    <Say voice="Polly.Joanna">
        Your voice inbox has {msg_count} stored message{'s' if msg_count != 1 else ''}.
        All data is persisted in Telnyx Storage, which is S3 compatible.
        This means your voicemails are available anytime, with zero database management.
    </Say>
    <Redirect>/voice</Redirect>"""
            else:
                texml = """
    <Say voice="Polly.Joanna">
        Unable to read storage stats at this time.
    </Say>
    <Redirect>/voice</Redirect>"""

        elif digits == "3":
            texml = """
    <Say voice="Polly.Joanna">
        Please leave a message after the beep. Press pound when finished.
    </Say>
    <Record 
        action="/recording-complete" 
        method="POST"
        maxLength="30"
        timeout="5"
        finishOnKey="#"
        playBeep="true"
    />
    <Redirect>/voice</Redirect>"""

        elif digits == "0":
            texml = """
    <Say voice="Polly.Joanna">Goodbye.</Say>
    <Hangup/>"""

        else:
            texml = """
    <Say voice="Polly.Joanna">Invalid selection.</Say>
    <Redirect>/voice</Redirect>"""

        await self._send_texml(send, texml)

    async def _handle_recording_complete(self, body, send):
        call_sid = body.get("CallSid", "unknown")
        from_number = body.get("From", "unknown")
        recording_url = body.get("RecordingUrl", "")
        recording_duration = body.get("RecordingDuration", "0")

        logging.info(f"🎙️ Recording: {recording_duration}s from {from_number}")

        if recording_url:
            store_voicemail_meta(
                call_sid, from_number, recording_url,
                recording_duration, self.telnyx_api_key
            )
            store_call_log(call_sid, "voicemail_saved", {
                "recording_url": recording_url,
                "duration": recording_duration,
            }, self.telnyx_api_key)

        texml = f"""
    <Say voice="Polly.Joanna">
        Thank you. Your {recording_duration} second message has been saved to Telnyx Storage.
        We will get back to you soon. Goodbye.
    </Say>
    <Hangup/>"""

        await self._send_texml(send, texml)

    async def _handle_status(self, body, send):
        call_sid = body.get("CallSid", "unknown")
        call_status = body.get("CallStatus", "unknown")

        store_call_log(call_sid, f"call_{call_status}", body, self.telnyx_api_key)
        await self._send_json(send, {"status": "ok"})

    async def _handle_debug_storage(self, send):
        import traceback
        results = {}
        api_key = self.telnyx_api_key or ''
        results['cfg_key_prefix'] = api_key[:15] + '...' if len(api_key) > 15 else api_key or 'NONE'
        results['cfg_key_len'] = len(api_key)

        env_vars = {k: v[:20] + '...' if len(v) > 20 else v
                    for k, v in os.environ.items()
                    if any(x in k.upper() for x in ['API', 'KEY', 'TELNYX', 'SECRET', 'TOKEN', 'AWS'])}
        results['relevant_env_vars'] = env_vars

        try:
            keys = s3_list(f"{STORAGE_PREFIX}/messages/", api_key)
            results['list_ok'] = True
            results['list_count'] = len(keys)
        except Exception as e:
            results['list_ok'] = False
            results['list_error'] = str(e)

        try:
            test_key = f"{STORAGE_PREFIX}/debug/test.json"
            test_body = b'{"test": "from_edge_compute"}'
            result = s3_request('PUT', test_key, test_body, 'application/json', api_key)
            results['put_status'] = result['status']
        except Exception as e:
            results['put_error'] = str(e)

        await self._send_json(send, results)

    async def _handle_health(self, send):
        try:
            msg_count = count_voicemails(self.telnyx_api_key)
            storage_status = "connected"
        except:
            msg_count = -1
            storage_status = "error"

        await self._send_json(send, {
            "status": "healthy",
            "app": "Voice Inbox",
            "description": "Business voicemail system — TeXML + Edge Compute + Telnyx Storage",
            "storage": {
                "status": storage_status,
                "bucket": STORAGE_BUCKET,
                "region": STORAGE_REGION,
                "voicemail_count": msg_count,
            },
            "owner_number": OWNER_NUMBER,
            "business_name": BUSINESS_NAME,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })

    @staticmethod
    def _speak_number(number: str) -> str:
        clean = number.lstrip('+')
        if len(clean) == 11 and clean.startswith('1'):
            return f"{clean[0]}. {clean[1:4]}. {clean[4:7]}. {clean[7:]}"
        elif len(clean) == 10:
            return f"{clean[:3]}. {clean[3:6]}. {clean[6:]}"
        else:
            return '. '.join(clean[i:i+2] for i in range(0, len(clean), 2))


def handler(request, context):
    return Function().handle(request, context) if False else None
