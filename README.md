# OpenClaw Crypto Agent (Server Trading + Telegram Control)

Project này hỗ trợ 3 luồng:
- `analysis`: quét web market, xếp hạng coin, xuất prompt cho Copilot
- `trading`: quét market, chọn 1 coin, tạo lệnh Binance Futures (isolated) với TP/SL
- `telegram`: điều khiển bot từ Telegram để chạy trading và nhận kết quả

## Quan trọng về Copilot/Claude trên server

- Server **không thể** dùng GitHub Copilot Chat như 1 API key.
- Nếu muốn LLM tự chạy trên server, bạn cần API thật (Anthropic/OpenAI...).
- Luồng trading hiện tại không phụ thuộc Copilot API; nó chạy từ dữ liệu thị trường + logic nội bộ.

## 1) Setup

```bash
cd openclaw_trading
cp .env.example .env
chmod +x run
```

## 2) Cấu hình `.env`

### Phân tích bằng Copilot (không cần API key Copilot)
- `LLM_PROVIDER=copilot`
- `TOP_N=10`

### Trading Binance Futures
- `BINANCE_API_KEY=...`
- `BINANCE_API_SECRET=...`
- `TRADE_USDT_AMOUNT=1`
- `LEVERAGE=3`
- `SL_PCT=3`
- `TP_PCT=6`
- `DRY_RUN=true` (khuyên dùng khi test)

### Telegram control
- `TELEGRAM_BOT_TOKEN=...`
- `TELEGRAM_ALLOWED_CHAT_ID=...` (khuyên đặt để chỉ bạn điều khiển bot)
- `TELEGRAM_POLL_INTERVAL_SEC=2`
- `AUTO_REENTER_ON_PROFIT=false`
- `PROFIT_REENTER_USDT=0.1`
- `TARGET_DECAY_AFTER_MIN=30`
- `TARGET_DECAY_STEP_USDT=0.02`
- `TARGET_DECAY_EVERY_MIN=10`
- `MIN_PROFIT_TARGET_USDT=0.02`
- `PNL_REFRESH_SEC=15`
- `PNL_MONITOR_MAX_MIN=45`
- `MAX_TRADE_CANDIDATES=20`
- `COPILOT_DAILY_QUERY_LIMIT=100`

## 3) Chạy lệnh

```bash
./run openclaw analysis
./run openclaw trading
./run openclaw telegram
```

## 4) Kết quả

- `analysis`: tạo `output_top_coins.json` + `copilot_prompt.txt`
- `trading`: tạo `trade_result.json`
- `telegram`: gửi lệnh `/run openclaw trading` hoặc `/trade` từ Telegram, bot trả về coin chọn + TP/SL + mode LIVE/DRY_RUN
- Khi nhận `/trade`, bot gửi ngay trạng thái `Đang làm việc...`
- Nếu đặt lệnh coin hiện tại lỗi, bot tự thử coin futures kế tiếp
- Bot refresh PnL theo `PNL_REFRESH_SEC` trong tối đa `PNL_MONITOR_MAX_MIN`
- Sau `TARGET_DECAY_AFTER_MIN`, target profit giảm dần theo `TARGET_DECAY_STEP_USDT` mỗi `TARGET_DECAY_EVERY_MIN`
- Có thêm `/status` để kiểm tra bot còn online
- Có thêm `/aiusage` để xem usage Copilot theo tracker cục bộ (ước lượng)

## 5) Chuyển từ test sang live

1. Giữ `DRY_RUN=true` để kiểm tra log và `trade_result.json`.
2. Khi mọi thứ đúng, đổi `DRY_RUN=false` để bot vào lệnh thật.
3. Nếu `DRY_RUN=false` nhưng số dư futures không đủ, bot tự chuyển paper trade và báo rõ lý do trong kết quả.

## Cảnh báo

- Bot chỉ dùng cho nghiên cứu/thử nghiệm, không đảm bảo lợi nhuận.
- Futures có rủi ro cao; luôn giới hạn vốn nhỏ và kiểm tra API permissions.
