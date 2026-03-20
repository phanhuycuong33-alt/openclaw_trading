#!/bin/bash
#
# Setup script for OpenClaw Crypto Trading Bot
# Usage: ./setup.sh
#

set -e  # Exit on error

echo "=================================="
echo "OpenClaw Bot - Setup Script"
echo "=================================="
echo ""

# Check Python version
echo "[1/5] Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION"

REQUIRED_VERSION="3.7"
if ! python3 -c "import sys; exit(0 if sys.version_info >= (3,7) else 1)"; then
    echo "❌ ERROR: Python 3.7+ required, found $PYTHON_VERSION"
    exit 1
fi
echo "✓ Python version OK"
echo ""

# Create virtual environment
echo "[2/5] Creating Python virtual environment..."
if [ -d ".venv" ]; then
    echo "Virtual environment already exists at .venv"
else
    python3 -m venv .venv
    echo "✓ Virtual environment created"
fi
echo ""

# Activate venv
echo "[3/5] Installing dependencies..."
source .venv/bin/activate || . .venv/Scripts/activate 2>/dev/null || true
pip install --upgrade pip setuptools wheel > /dev/null 2>&1
pip install -r requirements.txt
echo "✓ Dependencies installed"
echo ""

# Check .env file
echo "[4/5] Checking configuration..."
if [ ! -f ".env" ]; then
    echo "⚠ WARNING: .env file not found!"
    echo ""
    echo "You need to create .env with:"
    echo "  BINANCE_API_KEY=your_binance_api_key"
    echo "  BINANCE_API_SECRET=your_binance_api_secret"
    echo "  TELEGRAM_BOT_TOKEN=your_telegram_bot_token"
    echo "  TELEGRAM_ALLOWED_CHAT_ID=your_chat_id"
    echo "  DRY_RUN=true  (for testing)"
    echo ""
    cat > .env.example << 'EOF'
# Binance API
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_ALLOWED_CHAT_ID=your_chat_id_here

# Trading Settings
TRADE_USDT_AMOUNT=1
LEVERAGE=3
SL_PCT=3
TP_PCT=6
DRY_RUN=true

# Other Settings
ANTHROPIC_API_KEY=your_claude_api_key_here
MODEL=claude-3-5-sonnet-20241022
VS_CURRENCY=usd
TOP_N=10
AUTO_REENTER_ON_PROFIT=false
PROFIT_REENTER_USDT=0.1
TARGET_DECAY_AFTER_MIN=30
TARGET_DECAY_STEP_USDT=0.02
TARGET_DECAY_EVERY_MIN=10
MIN_PROFIT_TARGET_USDT=0.02
PNL_REFRESH_SEC=15
PNL_MONITOR_MAX_MIN=45
MAX_TRADE_CANDIDATES=20
COPILOT_DAILY_QUERY_LIMIT=100
EOF
    echo "✓ Created .env.example - copy and edit to create .env"
else
    echo "✓ .env file found"
fi
echo ""

# Validate imports
echo "[5/5] Validating Python environment..."
.venv/bin/python -c "
import sys
try:
    import binance
    print('✓ python-binance OK')
    import requests
    print('✓ requests OK')
    import dotenv
    print('✓ python-dotenv OK')
    import anthropic
    print('✓ anthropic OK')
    print('')
    print('All dependencies validated!')
except ImportError as e:
    print(f'❌ Import error: {e}')
    sys.exit(1)
"

echo ""
echo "=================================="
echo "✓ Setup Complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env"
echo "2. Edit .env with your API keys"
echo "3. Run: ./run openclaw telegram"
echo ""
