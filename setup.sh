#!/usr/bin/env bash
# Voice Inbox — One-command setup
# Usage: ./setup.sh

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${BOLD}[setup]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }

# ── Load .env ─────────────────────────────────────────────────────────────────
if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        warn ".env not found — copying from .env.example"
        cp .env.example .env
        warn "Edit .env with your values, then re-run this script."
        exit 1
    else
        fail ".env not found. Create it with TELNYX_API_KEY, OWNER_NUMBER, PHONE_NUMBER, etc."
    fi
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

# ── Validate required vars ────────────────────────────────────────────────────
for var in TELNYX_API_KEY TELNYX_STORAGE_BUCKET OWNER_NUMBER PHONE_NUMBER BUSINESS_NAME; do
    if [[ -z "${!var:-}" || "${!var}" == *"XXXX"* || "${!var}" == "KEYxxxxx" ]]; then
        fail "$var is not set or still has placeholder value. Edit .env first."
    fi
done

ok "Config loaded"
log "  API key: ${TELNYX_API_KEY:0:8}..."
log "  Bucket:  $TELNYX_STORAGE_BUCKET"
log "  Owner:   $OWNER_NUMBER"
log "  Phone:   $PHONE_NUMBER"
log "  Business: $BUSINESS_NAME"
echo ""

# ── Check dependencies ─────────────────────────────────────────────────────────
for cmd in curl telnyx-edge; do
    if ! command -v "$cmd" &>/dev/null; then
        if [[ "$cmd" == "telnyx-edge" ]]; then
            fail "telnyx-edge CLI not found. Install it: https://developers.telnyx.com/docs/cli/installing-telnyx-cli"
        fi
        fail "$cmd is required but not found."
    fi
done
ok "Dependencies found"
echo ""

# ── Create Storage bucket ─────────────────────────────────────────────────────
log "Creating Storage bucket: $TELNYX_STORAGE_BUCKET ..."

BUCKET_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    "https://api.telnyx.com/v2/storage/buckets" \
    -H "Authorization: Bearer $TELNYX_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$TELNYX_STORAGE_BUCKET\", \"region\": \"us-central-1\"}")

if [[ "$BUCKET_RESP" == "201" ]]; then
    ok "Bucket created: $TELNYX_STORAGE_BUCKET"
elif [[ "$BUCKET_RESP" == "409" ]]; then
    ok "Bucket already exists: $TELNYX_STORAGE_BUCKET"
else
    warn "Bucket creation returned HTTP $BUCKET_RESP — it may already exist or need manual creation"
    warn "Create it at: https://portal.telnyx.com/#/app/storage"
fi
echo ""

# ── Deploy Edge Compute function ──────────────────────────────────────────────
log "Deploying Edge Compute function..."
DEPLOY_OUTPUT=$(telnyx-edge deploy 2>&1)
echo "$DEPLOY_OUTPUT"

# Extract function URL from deploy output
FUNC_URL=$(echo "$DEPLOY_OUTPUT" | grep -oE 'https://[a-zA-Z0-9._-]+\.telnyxcompute\.com' | head -1 || true)
if [[ -z "$FUNC_URL" ]]; then
    warn "Could not auto-detect function URL from deploy output."
    read -rp "Enter your Edge Compute function URL (e.g. https://my-func.telnyxcompute.com): " FUNC_URL
fi
ok "Function deployed: $FUNC_URL"
echo ""

# ── Set secrets ────────────────────────────────────────────────────────────────
log "Setting Edge Compute secrets..."

telnyx-edge secrets add TELNYX_API_KEY "$TELNYX_API_KEY" 2>/dev/null || \
telnyx-edge secrets set TELNYX_API_KEY "$TELNYX_API_KEY" 2>/dev/null || \
warn "Could not set TELNYX_API_KEY via CLI — set it manually in the portal"

telnyx-edge secrets add TELNYX_STORAGE_BUCKET "$TELNYX_STORAGE_BUCKET" 2>/dev/null || \
telnyx-edge secrets set TELNYX_STORAGE_BUCKET "$TELNYX_STORAGE_BUCKET" 2>/dev/null || true

telnyx-edge secrets add OWNER_NUMBER "$OWNER_NUMBER" 2>/dev/null || \
telnyx-edge secrets set OWNER_NUMBER "$OWNER_NUMBER" 2>/dev/null || true

telnyx-edge secrets add PHONE_NUMBER "$PHONE_NUMBER" 2>/dev/null || \
telnyx-edge secrets set PHONE_NUMBER "$PHONE_NUMBER" 2>/dev/null || true

telnyx-edge secrets add BUSINESS_NAME "$BUSINESS_NAME" 2>/dev/null || \
telnyx-edge secrets set BUSINESS_NAME "$BUSINESS_NAME" 2>/dev/null || true

ok "Secrets configured"
echo ""

# ── Create TeXML app ────────────────────────────────────────────────────────────
log "Creating TeXML application..."

TEXML_RESP=$(curl -s -X POST \
    "https://api.telnyx.com/v2/texml_applications" \
    -H "Authorization: Bearer $TELNYX_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
        \"friendly_name\": \"Voice Inbox Demo\",
        \"voice_url\": \"$FUNC_URL/voice\",
        \"voice_method\": \"POST\",
        \"status_callback\": \"$FUNC_URL/status\",
        \"status_callback_method\": \"POST\"
    }")

TEXML_ID=$(echo "$TEXML_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('id',''))" 2>/dev/null || true)

if [[ -n "$TEXML_ID" ]]; then
    ok "TeXML application created: $TEXML_ID"
else
    warn "Could not create TeXML app automatically."
    warn "Create it manually in the portal:"
    warn "  Voice webhook: $FUNC_URL/voice"
    warn "  Status callback: $FUNC_URL/status"
    warn "Then assign $PHONE_NUMBER to it."
    echo ""
fi

# ── Assign phone number ─────────────────────────────────────────────────────────
if [[ -n "$TEXML_ID" ]]; then
    log "Assigning $PHONE_NUMBER to TeXML app..."

    # Get phone number ID
    PHONE_CLEAN=$(echo "$PHONE_NUMBER" | sed 's/+//')
    PHONE_DATA=$(curl -s \
        "https://api.telnyx.com/v2/phone_numbers?filter[phone_number]=%2B$PHONE_CLEAN" \
        -H "Authorization: Bearer $TELNYX_API_KEY")
    PHONE_ID=$(echo "$PHONE_DATA" | python3 -c "import sys,json; d=json.load(sys.stdin); nums=d.get('data',[]); print(nums[0]['id'] if nums else '')" 2>/dev/null || true)

    if [[ -n "$PHONE_ID" ]]; then
        UPDATE_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
            "https://api.telnyx.com/v2/phone_numbers/$PHONE_ID" \
            -H "Authorization: Bearer $TELNYX_API_KEY" \
            -H "Content-Type: application/json" \
            -d "{\"connection_id\": \"$TEXML_ID\"}")
        if [[ "$UPDATE_RESP" == "200" ]]; then
            ok "Phone number assigned to TeXML app"
        else
            warn "Phone number assignment returned HTTP $UPDATE_RESP"
            warn "Assign $PHONE_NUMBER manually in the portal"
        fi
    else
        warn "Could not find $PHONE_NUMBER in your account"
        warn "Assign it manually to TeXML app $TEXML_ID in the portal"
    fi
fi

echo ""
echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}✓ Voice Inbox is ready!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  📞 Call: ${BOLD}$PHONE_NUMBER${NC}"
echo -e "  🌐 Dashboard: ${BOLD}$FUNC_URL/dashboard${NC}"
echo -e "  🔑 Admin (call from): ${BOLD}$OWNER_NUMBER${NC}"
echo ""
echo -e "  Verify health: curl $FUNC_URL/health"
echo ""
