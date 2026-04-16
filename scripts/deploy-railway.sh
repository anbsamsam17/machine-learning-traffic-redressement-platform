#!/bin/bash
# === Railway Deployment Script ===
# Usage: bash scripts/deploy-railway.sh
#
# Prerequisites:
#   1. railway login (done once)
#   2. railway link (link to existing project)

set -e

echo "================================================"
echo "  MDL Redressement — Railway Deployment"
echo "================================================"
echo ""

# Check Railway CLI
if ! command -v railway &> /dev/null; then
    echo "ERROR: Railway CLI not found. Install with: npm install -g @railway/cli"
    exit 1
fi

echo "[1/4] Setting environment variables on API service..."
echo "  -> Switch to your API service in Railway dashboard first"
echo ""

# These will be set via Railway dashboard or CLI
cat << 'VARS'
=== Variables to set on API service ===
CUDA_VISIBLE_DEVICES=-1
TF_CPP_MIN_LOG_LEVEL=3
TF_ENABLE_ONEDNN_OPTS=0
TF_XLA_FLAGS=--tf_xla_enable_xla_devices=false
JWT_SECRET=<generate with: openssl rand -hex 32>
WORKSPACE_ROOT=/data/mdl_workdir
SESSION_TTL_SECONDS=7200
MAX_UPLOAD_MB=500
MAX_TRAINING_MINUTES=60
LOG_LEVEL=INFO
ENVIRONMENT=production
PORT=8000

=== Variables to set on Web service ===
NEXT_PUBLIC_API_URL=<Railway API service URL>
PORT=3000

=== Redis ===
Add Redis plugin in Railway dashboard → it auto-injects REDIS_URL
VARS

echo ""
echo "[2/4] To deploy, use Railway dashboard:"
echo "  1. Create a new project on railway.app"
echo "  2. Add Redis plugin (click + New → Database → Redis)"
echo "  3. Add API service (click + New → GitHub Repo → select repo)"
echo "     - Set root directory: apps/api"
echo "     - Set Dockerfile path: infra/Dockerfile.api.railway"
echo "     - Set all env vars above"
echo "  4. Add Web service (same repo, new service)"
echo "     - Set root directory: apps/web"
echo "     - Set Dockerfile path: infra/Dockerfile.web.railway"
echo "     - Set NEXT_PUBLIC_API_URL to the API service public URL"
echo "  5. Add custom domain on the Web service"
echo ""
echo "[3/4] DNS Configuration:"
echo "  On your Hostinger domain DNS settings:"
echo "  - Add CNAME record: @ → <railway-provided-domain>.up.railway.app"
echo "  - Or A record if Railway provides an IP"
echo "  Railway auto-provisions HTTPS certificate for custom domains"
echo ""
echo "[4/4] After deployment:"
echo "  - Create first admin user via /register"
echo "  - Test full workflow: upload → mapping → config → train → evaluate"
echo "  - Check logs in Railway dashboard"
echo ""
echo "Done! Your SaaS will be live at https://your-domain.com"
