# OpenClaw Crypto Bot - Deployment Guide

## Quick Start

### Local Machine
```bash
git clone https://github.com/yourusername/openclaw-crypto-agent.git
cd openclaw-crypto-agent
bash setup.sh
cp .env.example .env
# Edit .env with your API keys
./run openclaw telegram
```

### Server Deployment

#### 1. Prerequisites
- Ubuntu/Debian 20.04+ or similar Linux
- SSH access to server
- Python 3.7+ (`python3 --version`)
- Git installed

#### 2. Clone and Setup
```bash
# SSH into your server
ssh user@your-server-ip

# Clone repository
git clone https://github.com/yourusername/openclaw-crypto-agent.git
cd openclaw-crypto-agent

# Run automatic setup
bash setup.sh
```

#### 3. Configure Environment
```bash
# Copy example config
cp .env.example .env

# Edit with your credentials
nano .env
```

**Required environment variables:**
```
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_ALLOWED_CHAT_ID=your_telegram_chat_id
DRY_RUN=true  # Start with dry-run (paper trading)
```

#### 4. Test Run
```bash
# Test market analysis
./run openclaw analysis

# Test trading (paper mode)
./run openclaw trading

# Test Telegram bot - keep it running for 30 seconds
timeout 30 ./run openclaw telegram
```

#### 5. Run as Service (systemd)

Create `/etc/systemd/system/openclaw-bot.service`:
```ini
[Unit]
Description=OpenClaw Crypto Trading Bot
After=network.target

[Service]
Type=simple
User=openclaw
WorkingDirectory=/home/openclaw/openclaw-crypto-agent
ExecStart=/home/openclaw/openclaw-crypto-agent/.venv/bin/python /home/openclaw/openclaw-crypto-agent/telegram_control.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable openclaw-bot
sudo systemctl start openclaw-bot
sudo systemctl status openclaw-bot
sudo journalctl -u openclaw-bot -f  # View logs
```

#### 6. Run with tmux (Simple Alternative)
```bash
tmux new-session -d -s openclaw
tmux send-keys -t openclaw "cd ~/openclaw-crypto-agent && ./run openclaw telegram" Enter
tmux attach -t openclaw  # View bot
# Ctrl+B then D to detach
tmux kill-session -t openclaw  # Stop bot
```

#### 7. Security Best Practices
- [ ] Use `.env` with read-only permissions (not in git)
- [ ] Rotate API keys periodically
- [ ] Start with `DRY_RUN=true` for testing
- [ ] Use isolated Binance API keys (IP whitelist)
- [ ] Monitor bot logs regularly
- [ ] Set up SSH key-based auth (no passwords)

## File Structure
```
.
├── setup.sh                 # Automatic setup script
├── run                      # Main entry point (analysis/trading/telegram)
├── requirements.txt         # Python dependencies
├── .env.example            # Configuration template
├── .env                    # Your secrets (DO NOT commit!)
├── telegram_control.py     # Telegram bot controller
├── trade_openclaw.py       # Trading logic
├── main.py                 # Analysis mode
├── src/
│   ├── analyzer.py         # Coin scoring algorithm
│   ├── binance_trader.py   # Binance API wrapper
│   ├── config.py           # Settings loader
│   ├── usage_tracker.py    # Copilot usage counter
│   └── ...
└── README.md               # This file
```

## Mode Reference

### Analysis Mode
Scan CoinGecko for top pump-probability coins:
```bash
./run openclaw analysis
# Output: output_top_coins.json, copilot_prompt.txt
```

### Trading Mode
Execute a single trade based on analysis:
```bash
./run openclaw trading
# Output: trade_result.json
```

### Telegram Control Mode
Run persistent bot controlled via Telegram:
```bash
./run openclaw telegram
```

**Available commands:**
- `/trade` - Execute a trade
- `/status` - Bot status
- `/aiusage` - Copilot usage estimate
- `/stop` - Gracefully shutdown bot

## Troubleshooting

### "Module not found" errors
```bash
source .venv/bin/activate  # Ensure venv is active
pip install -r requirements.txt
```

### Telegram bot not responding
- Check bot token is correct in `.env`
- Check chat ID matches `TELEGRAM_ALLOWED_CHAT_ID`
- Verify internet connection
- Check logs: `tail -f openclaw_bot.log`

### Binance API errors
- Verify API key and secret are correct
- Check IP address is whitelisted in Binance security settings
- Ensure account has Futures trading enabled
- Check available USDT balance for margin

### Bot auto-executing trades on startup
This was fixed in the latest version - bot skips old messages and only processes new Telegram commands.

## Performance Notes

- **PNL Refresh**: Every 15 seconds (configurable via `PNL_REFRESH_SEC`)
- **Telegram Poll**: Every 2 seconds (configurable via `TELEGRAM_POLL_INTERVAL_SEC`)
- **Trade Execution**: ~5-10 seconds depending on network
- **Memory**: ~80-120 MB when running

## Monitoring

### Check if bot is running
```bash
ps aux | grep telegram_control
ps aux | grep "run openclaw"
```

### View logs
```bash
# systemd service
sudo journalctl -u openclaw-bot -f

# Manual tmux session
tmux capture-pane -t openclaw -p
```

### Manual stop
```bash
# Via Telegram: send /stop
# Via terminal: Ctrl+C
# Force kill:
pkill -9 python  # Caution: kills all Python processes!
```

## Updating Code

```bash
cd ~/openclaw-crypto-agent
git pull origin main
bash setup.sh  # Re-install dependencies if changed
```

## Support

For issues:
1. Check logs for error messages
2. Verify `.env` configuration
3. Test Binance API connection separately
4. Ensure Python version >= 3.7
