# Voice Inbox — Telnyx Demo

A business voicemail system that demonstrates three Telnyx products working together in under 200 lines of Python.

| Product | Role |
|---|---|
| **TeXML** | Declarative IVR — call routing, recording, playback |
| **Edge Compute** | Serverless runtime — always-on, zero DevOps |
| **Storage** | S3-compatible persistence — voicemails survive restarts |

**Caller experience:**  
> "Hello, you've reached Acme Corp. Please leave a message after the beep."  
→ Voicemail saved to Storage → "Thank you. Your message has been saved."

**Owner experience (call from your own number):**  
> "Welcome back. You have 3 messages."  
→ Press 1 to hear latest voicemail, 2 for stats, 3 to leave a note

**Web dashboard:** Live voicemail inbox at `/dashboard` — auto-refreshes every 10s.

---

## 🎧 Try the Live Demo

**Call +1 929-219-1811** — it's always-on (Edge Compute, no tunnel needed).

- From any number → leave a voicemail
- Call again from the same number to hear it played back  
- Visit the **[live dashboard](https://seng-75-texml-dc36389d-3.telnyxcompute.com/dashboard)**

---

## Prerequisites

- [Telnyx account](https://telnyx.com/sign-up) with:
  - A phone number purchased
  - API key
  - Edge Compute enabled
  - Storage enabled
- [Telnyx Edge CLI](https://developers.telnyx.com/docs/cli/installing-telnyx-cli) installed (`telnyx-edge`)
- `curl` (for setup script)
- Python 3.9+ (for local testing only)

---

## Setup (10 minutes)

### 1. Clone the repo

```bash
git clone https://github.com/team-telnyx/voice-inbox-demo.git
cd voice-inbox-demo
```

### 2. Set your configuration

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
TELNYX_API_KEY=KEYxxxxx               # From portal.telnyx.com → API Keys
TELNYX_STORAGE_BUCKET=voice-inbox     # Storage bucket name (will be created)
OWNER_NUMBER=+1XXXXXXXXXX             # YOUR phone number — gets the admin menu
PHONE_NUMBER=+1XXXXXXXXXX             # The Telnyx number customers call
BUSINESS_NAME=Acme Corp               # What the greeting says to callers
```

### 3. Run the setup script

```bash
chmod +x setup.sh
./setup.sh
```

This will:
1. Create a Storage bucket in `us-central-1`
2. Deploy the Edge Compute function
3. Inject your secrets into Edge Compute
4. Create a TeXML application
5. Link your phone number to the TeXML app

### 4. Call it

Call your **PHONE_NUMBER** from any phone → leave a voicemail.  
Call from your **OWNER_NUMBER** → get the admin menu.

Visit `https://<your-function-url>/dashboard` for the live web inbox.

---

## Manual Setup

If you prefer step-by-step:

### 1. Create Storage bucket

In the [Telnyx portal](https://portal.telnyx.com/#/app/storage), create a bucket in region `us-central-1`.

### 2. Deploy the function

```bash
telnyx-edge login
telnyx-edge deploy
# Note the function URL from the output
```

### 3. Set secrets

```bash
telnyx-edge secrets add TELNYX_API_KEY KEYxxxxx
telnyx-edge secrets add TELNYX_STORAGE_BUCKET voice-inbox
telnyx-edge secrets add OWNER_NUMBER +1XXXXXXXXXX
telnyx-edge secrets add PHONE_NUMBER +1XXXXXXXXXX
telnyx-edge secrets add BUSINESS_NAME "Acme Corp"
```

### 4. Create TeXML application

In the portal → **Voice** → **TeXML Apps**, create an app:
- Voice webhook URL: `https://<your-function-url>/voice`
- Status callback URL: `https://<your-function-url>/status`

### 5. Assign phone number

Assign your phone number to the TeXML app.

---

## Project Structure

```
voice-inbox/
├── function/
│   ├── func.py          # Main app — TeXML handlers + Storage + Dashboard
│   └── __init__.py
├── func.toml            # Edge Compute config
├── pyproject.toml       # Python project metadata
├── setup.sh             # One-command provisioning script
├── .env.example         # Config template
└── README.md
```

---

## How It Works

```
Caller dials → Telnyx routes via TeXML → Edge Compute function
                                              ↓
                                    Caller leaves voicemail
                                              ↓
                                    Saved to Telnyx Storage
                                              ↓
                                    Owner calls → reads from Storage → plays back
```

No database. No persistent server. No tunnel. All state in **Telnyx Storage**.

---

## Owner Menu

| Key | Action |
|---|---|
| 1 | Hear latest voicemail |
| 2 | Message count + storage stats |
| 3 | Leave a voicemail yourself |
| 0 | Hang up |

---

## Dashboard

Visit `https://<your-function-url>/dashboard`:
- Live voicemail inbox with audio playback
- Call activity log
- Storage health check

---

## TeXML vs Call Control

| | TeXML (this demo) | Call Control API |
|---|---|---|
| Model | Declarative XML | Imperative REST |
| Infrastructure | Edge Compute (serverless) | Local server + ngrok |
| Persistence | Telnyx Storage (built-in) | DIY |
| Lines of code | ~200 | 800+ |
| Best for | IVRs, voicemail, simple flows | Complex real-time apps |

---

## Troubleshooting

**Calls not routing to my function?**  
Verify the TeXML app webhook URL matches your function URL exactly.

**Voicemails not saving?**  
Check secrets are set and the bucket exists:
```bash
curl https://<your-function-url>/debug/storage
```

**Dashboard shows no data?**  
Make sure `TELNYX_API_KEY` has Storage permissions in the portal.

**Recording not playing?**  
The app fetches fresh signed URLs from the Telnyx Recordings API — recordings expire after 30 days.

---

## License

MIT
