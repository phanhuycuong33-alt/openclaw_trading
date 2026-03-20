"""
OpenClaw Crypto Trading Bot - Server Deployment Quick Reference
"""

# File Overview

requirements.txt
  - All Python dependencies (36 packages)
  - Use: pip install -r requirements.txt

setup.sh  ⭐ MAIN DEPLOYMENT SCRIPT
  - Checks Python 3.7+
  - Creates virtual environment
  - Installs dependencies
  - Validates imports
  - Creates .env.example template
  - Usage: bash setup.sh

DEPLOYMENT.md  ⭐ COMPLETE DEPLOYMENT GUIDE
  - Local setup instructions
  - Server SSH deployment
  - systemd service configuration
  - tmux session management
  - Security best practices
  - Troubleshooting guide

.gitignore
  - Excludes .env (API keys - CRITICAL!)
  - Excludes .venv, __pycache__, output files
  - Prevents accidental secret commits

.env.example
  - Template for configuration
  - All required variables documented
  - Safe to commit (no real secrets)

push-to-github.sh
  - Helper script to push to GitHub
  - Usage: bash push-to-github.sh https://github.com/yourusername/repo.git


# Server Setup Workflow

1. On GitHub: Create empty repo at https://github.com/new
2. Push code:
   bash push-to-github.sh https://github.com/yourusername/openclaw-crypto-agent.git

3. On your server:
   git clone https://github.com/yourusername/openclaw-crypto-agent.git
   cd openclaw-crypto-agent
   bash setup.sh
   cp .env.example .env
   nano .env  # Add your API keys
   ./run openclaw telegram


# What's Protected in .gitignore

❌ NOT in repository (protected):
  - .env (contains API keys, chat IDs)
  - output_top_coins.json (generated data)
  - trade_result.json (generated data)
  - usage_stats.json (generated data)
  - .venv/ (environment-specific)
  - __pycache__/ (compiled Python)

✅ In repository (safe):
  - .env.example (template only)
  - All Python source code
  - setup.sh & DEPLOYMENT.md (instructions)
  - requirements.txt (dependency list)


# What setup.sh Does

Step 1: Validates Python 3.7+
Step 2: Creates (or reuses) .venv virtual environment
Step 3: Installs all 36 dependencies from requirements.txt
Step 4: Tests all imports (binance, requests, dotenv, anthropic)
Step 5: Creates .env.example if not present

Total time: ~1-2 minutes (depending on internet speed)


# Key Dependencies

Core trading:
  - python-binance (Binance Futures API)
  - requests (HTTP client)
  - python-dotenv (Environment config)

LLM/Analysis:
  - anthropic (Claude API)
  - pydantic (Data validation)

Data processing:
  - dateparser, pytz (Timezone handling)
  - aiohttp, websockets (Async networking)
  - pycryptodome (Cryptography)

Full list: requirements.txt


# Setting Up on Fresh Server

$ ssh user@server
$ git clone https://github.com/yourusername/openclaw-crypto-agent.git
$ cd openclaw-crypto-agent
$ bash setup.sh
✓ Setup complete

$ cp .env.example .env
$ nano .env  # Add your credentials:
  BINANCE_API_KEY=pk3...
  BINANCE_API_SECRET=qR...
  TELEGRAM_BOT_TOKEN=820...
  TELEGRAM_ALLOWED_CHAT_ID=763...

$ ./run openclaw telegram
✓ Bot running - send /trade via Telegram


# Deployment Options

Option A: systemd service (recommended for servers)
  - Bot starts automatically on reboot
  - Easy to manage: systemctl start/stop/status
  - Logs via: journalctl -u openclaw-bot -f
  - See DEPLOYMENT.md for full config

Option B: tmux session (simple, interactive)
  - tmux new-session -d -s openclaw
  - tmux send-keys -t openclaw "cd ~/openclaw-crypto-agent && ./run openclaw telegram" Enter
  - tmux attach -t openclaw  # View
  - Ctrl+B D to detach

Option C: Direct execution
  - nohup ./run openclaw telegram > bot.log 2>&1 &
  - Or: screen -S openclaw


# Monitoring Bot Health

Check if running:
  ps aux | grep telegram_control
  ps aux | grep "run openclaw"

View logs:
  # systemd
  sudo journalctl -u openclaw-bot -f
  # or from bot dir
  tail -f *.log

Test commands:
  /trade       - Execute trade
  /status      - Status check
  /aiusage     - Show Copilot usage
  /stop        - Stop bot gracefully

Manual stop:
  Ctrl+C in terminal, or send /stop via Telegram


# Security Checklist

Before production:
  ✓ .env created & never committed
  ✓ Binance API key has IP whitelist
  ✓ Telegram bot token is secret
  ✓ DRY_RUN=true for initial testing
  ✓ Only isolated futures, small amounts
  ✓ API keys regenerated if ever exposed
  ✓ .env file permissions: chmod 600 .env
  ✓ SSH key-based auth (not password)


# Troubleshooting

"ModuleNotFoundError"
  → source .venv/bin/activate
  → pip install -r requirements.txt

"Telegram bot not responding"
  → Check TELEGRAM_BOT_TOKEN correct
  → Check TELEGRAM_ALLOWED_CHAT_ID correct
  → Check internet connection

"Binance API error"
  → Verify API key/secret
  → Check IP whitelisted
  → Ensure Futures trading enabled
  → Check account has balance

Bot stopped unexpectedly
  → Check logs: journalctl -u openclaw-bot
  → Restart: systemctl restart openclaw-bot
  → Manual restart: ./run openclaw telegram


# Updating Code Later

$ cd openclaw-crypto-agent
$ git pull origin master
$ bash setup.sh  # Re-install if dependencies changed
$ systemctl restart openclaw-bot  # Restart service


# Support References

- Binance API: https://binance-docs.github.io/apidocs/
- Telegram Bot API: https://core.telegram.org/bots/api
- CoinGecko API: https://docs.coingecko.com/
- DEPLOYMENT.md: Full deployment guide in repo


Created: 2026-03-20
Version: 1.0
Ready for production deployment
