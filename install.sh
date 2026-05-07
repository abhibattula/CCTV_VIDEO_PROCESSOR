#!/usr/bin/env bash
# RasPi CCTV Analyst — one-command installer
# Run as: bash install.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================"
echo "  RasPi CCTV Analyst — Installer"
echo "================================================"

# Architecture check
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
    echo "⚠  WARNING: Not running on aarch64/arm64 (detected: $ARCH)"
    echo "   This system is optimised for Raspberry Pi 5 aarch64."
    read -rp "   Continue anyway? [y/N] " yn
    [[ "$yn" =~ ^[Yy]$ ]] || exit 1
fi

# System packages
echo ""
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    ffmpeg \
    python3-pip \
    python3-venv \
    openssl \
    2>/dev/null || true

# Python virtual environment
echo ""
echo "[2/6] Creating Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
deactivate

# Data directories
echo ""
echo "[3/6] Creating data directories..."
mkdir -p data/uploads data/jobs data/previews outputs ssl

# TLS certificate (ISSUE-01 — required for PWA service worker)
echo ""
echo "[4/6] Generating TLS certificate..."
if [ ! -f "ssl/cert.pem" ]; then
    HOSTNAME=$(hostname)
    openssl req -x509 -newkey rsa:4096 -nodes -days 3650 \
        -keyout ssl/key.pem \
        -out ssl/cert.pem \
        -subj "/CN=${HOSTNAME}.local" \
        -addext "subjectAltName=DNS:${HOSTNAME}.local,DNS:localhost,IP:127.0.0.1" \
        2>/dev/null
    echo "   Certificate generated for ${HOSTNAME}.local"
else
    echo "   Certificate already exists — skipping"
fi

# Database initialisation
echo ""
echo "[5/6] Initialising database..."
source venv/bin/activate
python -c "from app.database import init_db; init_db(); print('   Database ready.')"
deactivate

# Generate PWA icons if Pillow available
echo ""
echo "[5b] Generating PWA icons..."
source venv/bin/activate
pip install --quiet Pillow 2>/dev/null || true
python generate_icons.py 2>/dev/null || echo "   Icons skipped (Pillow unavailable)"
deactivate

# Systemd service
echo ""
echo "[6/6] Installing systemd service..."
INSTALL_DIR="$SCRIPT_DIR"
SERVICE_FILE="/etc/systemd/system/cctv-analyst.service"

sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=RasPi CCTV Analyst
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart="${INSTALL_DIR}/venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 5000 --workers 1 --ssl-keyfile ssl/key.pem --ssl-certfile ssl/cert.pem
MemoryMax=1400M
CPUQuota=360%
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable cctv-analyst
sudo systemctl start cctv-analyst

echo ""
echo "================================================"
echo "  Installation complete!"
echo ""
HOSTNAME=$(hostname)
echo "  Dashboard: https://${HOSTNAME}.local:5000"
echo ""
echo "  RAM mode: $(venv/bin/python -c "from app.config import RAM_MODE; print(RAM_MODE)" 2>/dev/null || echo 'unknown')"
echo ""
echo "  First visit: accept the certificate warning in your browser."
echo "  Tip: Install as a PWA from the browser for the best experience."
echo "================================================"
