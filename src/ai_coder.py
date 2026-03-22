"""ai_coder.py — Generate runnable Python code from a natural-language description.

Flow:
  1. Try Anthropic Claude API if ANTHROPIC_API_KEY is present and non-placeholder.
  2. Try Groq API (free) if GROQ_API_KEY is present.
  3. Fall back to a smart keyword-based template generator.

The caller receives a ready-to-save Python source string.
"""
from __future__ import annotations

import os
import re
import textwrap


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_code(description: str) -> tuple[str, str]:
    """Return (python_source, info_line).

    info_line describes which engine was used, e.g.
      "claude-3-5-sonnet-20241022" | "groq/llama3-70b" | "template"
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("MODEL", "claude-3-5-sonnet-20241022").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()

    # 1) Try Anthropic Claude
    if api_key and api_key != "your_claude_api_key_here":
        code, ok = _generate_with_claude(description, api_key, model)
        if ok:
            return code, model

    # 2) Try Groq free API
    if groq_key:
        code, ok = _generate_with_groq(description, groq_key)
        if ok:
            return code, "groq/llama-3.3-70b"

    # 3) Smart template fallback
    code = _smart_template(description)
    return code, "template"


def generate_code_from_error(
    description: str,
    previous_code: str,
    error_output: str,
) -> tuple[str, str]:
    """Regenerate code by incorporating runtime error feedback.

    Returns (python_source, engine_info).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    model = os.getenv("MODEL", "claude-3-5-sonnet-20241022").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()

    # 1) Claude repair pass
    if api_key and api_key != "your_claude_api_key_here":
        code, ok = _repair_with_claude(description, previous_code, error_output, api_key, model)
        if ok:
            return code, f"{model}/repair"

    # 2) Groq repair pass
    if groq_key:
        code, ok = _repair_with_groq(description, previous_code, error_output, groq_key)
        if ok:
            return code, "groq/llama-3.1-70b/repair"

    # 3) Rule-based repair fallback
    repaired = _rule_based_repair(description, previous_code, error_output)
    return repaired, "template/repair"


# ---------------------------------------------------------------------------
# Anthropic Claude
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Bạn là một Python developer cấp cao.
Nhiệm vụ: Viết 1 script Python hoàn chỉnh, có thể chạy ngay (runnable) theo mô tả người dùng.

Quy tắc BẮT BUỘC:
- Chỉ trả về code Python, KHÔNG giải thích, KHÔNG markdown, KHÔNG ``` fence.
- Code phải có if __name__ == '__main__' block.
- Có comment ngắn giải thích từng phần.
- Nếu cần thư viện bên ngoài, thêm comment # pip install <pkg> ở đầu file.
- Xử lý exception cơ bản.
- In kết quả ra stdout để có thể kiểm tra.
"""


def _generate_with_claude(description: str, api_key: str, model: str) -> tuple[str, bool]:
    try:
        from anthropic import Anthropic  # type: ignore
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=2000,
            temperature=0.2,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Hãy viết script: {description}"}],
        )
        parts = [getattr(b, "text", "") for b in message.content if getattr(b, "text", "")]
        raw = "\n".join(parts).strip()
        code = _strip_markdown(raw)
        if "def " in code or "import " in code or "print(" in code:
            return code, True
        return "", False
    except Exception:
        return "", False


def _repair_with_claude(
    description: str,
    previous_code: str,
    error_output: str,
    api_key: str,
    model: str,
) -> tuple[str, bool]:
    try:
        from anthropic import Anthropic  # type: ignore

        client = Anthropic(api_key=api_key)
        prompt = (
            "Hãy sửa script Python bị lỗi runtime.\n"
            "Yêu cầu:\n"
            "- Chỉ trả về code Python đã sửa, không markdown, không giải thích.\n"
            "- Giữ mục tiêu gốc theo mô tả người dùng.\n"
            "- Ưu tiên code chạy được ngay trong môi trường local.\n"
            "- Nếu lỗi do thiếu package, hãy sửa code để có fallback an toàn hoặc giảm phụ thuộc ngoài.\n\n"
            f"Mô tả dự án:\n{description}\n\n"
            f"Lỗi runtime:\n{error_output[:3000]}\n\n"
            f"Code cũ:\n{previous_code[:12000]}"
        )

        message = client.messages.create(
            model=model,
            max_tokens=2400,
            temperature=0.1,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        parts = [getattr(b, "text", "") for b in message.content if getattr(b, "text", "")]
        raw = "\n".join(parts).strip()
        code = _strip_markdown(raw)
        if "def " in code or "import " in code or "print(" in code:
            return code, True
        return "", False
    except Exception:
        return "", False


# ---------------------------------------------------------------------------
# Groq free API (OpenAI-compatible)
# ---------------------------------------------------------------------------

def _generate_with_groq(description: str, groq_key: str) -> tuple[str, bool]:
    try:
        import requests  # type: ignore
        # Note: Groq models change frequently; using llama-3.3-70b-versatile
        model = "llama-3.3-70b-versatile"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Hãy viết script: {description}"},
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        code = _strip_markdown(raw)
        if "def " in code or "import " in code or "print(" in code:
            return code, True
        return "", False
    except Exception:
        return "", False


def _repair_with_groq(
    description: str,
    previous_code: str,
    error_output: str,
    groq_key: str,
) -> tuple[str, bool]:
    try:
        import requests  # type: ignore

        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Sửa script Python bị lỗi runtime. Chỉ trả về code đã sửa.\n\n"
                        f"Mô tả:\n{description}\n\n"
                        f"Lỗi:\n{error_output[:3000]}\n\n"
                        f"Code cũ:\n{previous_code[:12000]}"
                    ),
                },
            ],
            "temperature": 0.1,
            "max_tokens": 2400,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        code = _strip_markdown(raw)
        if "def " in code or "import " in code or "print(" in code:
            return code, True
        return "", False
    except Exception:
        return "", False


# ---------------------------------------------------------------------------
# Smart keyword-based template fallback
# ---------------------------------------------------------------------------

def _smart_template(description: str) -> str:
    low = description.lower()

    # ---- trade / crypto / coin ----------------------------------------
    if any(k in low for k in ["trade", "coin", "crypto", "btc", "binance", "spot", "future"]):
        return textwrap.dedent(f"""\
            # AUTO-GENERATED: {description}
            # pip install requests pandas ta

            import requests
            import pandas as pd
            from datetime import datetime


            SYMBOL = "BTCUSDT"
            INTERVAL = "15m"
            LIMIT = 100


            def fetch_klines(symbol: str, interval: str, limit: int) -> pd.DataFrame:
                url = "https://fapi.binance.com/fapi/v1/klines"
                params = {{"symbol": symbol, "interval": interval, "limit": limit}}
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                cols = ["ts","open","high","low","close","volume",
                        "close_ts","qv","trades","tbbv","tbqv","ignore"]
                df = pd.DataFrame(resp.json(), columns=cols)
                for c in ["open","high","low","close","volume"]:
                    df[c] = df[c].astype(float)
                df["dt"] = pd.to_datetime(df["ts"], unit="ms")
                return df


            def analyse(df: pd.DataFrame) -> dict:
                close = df["close"]
                last = close.iloc[-1]
                ema20 = close.ewm(span=20).mean().iloc[-1]
                ema50 = close.ewm(span=50).mean().iloc[-1]
                delta = close.diff()
                gain = delta.clip(lower=0)
                loss = -delta.clip(upper=0)
                rs = gain.rolling(14).mean() / loss.rolling(14).mean()
                rsi = (100 - 100 / (1 + rs)).iloc[-1]
                return {{
                    "symbol": SYMBOL,
                    "price": round(last, 4),
                    "ema20": round(ema20, 4),
                    "ema50": round(ema50, 4),
                    "rsi": round(rsi, 2),
                    "signal": "BUY" if ema20 > ema50 and rsi < 60 else "WAIT",
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }}


            if __name__ == "__main__":
                df = fetch_klines(SYMBOL, INTERVAL, LIMIT)
                result = analyse(df)
                print("=== Crypto Analysis ===")
                for k, v in result.items():
                    print(f"  {{k}}: {{v}}")
        """)

    # ---- website / web / flask / api ----------------------------------
    if any(k in low for k in ["website", "web", "flask", "api", "server", "http", "endpoint"]):
        return textwrap.dedent(f"""\
            # AUTO-GENERATED: {description}
            # pip install flask

            from flask import Flask, jsonify, request

            app = Flask(__name__)

            DATA = []


            @app.route("/")
            def index():
                return jsonify({{"status": "ok", "message": "Hello from auto-generated API!"}})


            @app.route("/items", methods=["GET"])
            def get_items():
                return jsonify({{"items": DATA, "total": len(DATA)}})


            @app.route("/items", methods=["POST"])
            def add_item():
                body = request.json or {{}}
                item = {{"id": len(DATA) + 1, **body}}
                DATA.append(item)
                return jsonify({{"created": item}}), 201


            if __name__ == "__main__":
                print("Starting server on http://0.0.0.0:5000")
                app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
        """)

    # ---- scraper / crawl / download -----------------------------------
    if any(k in low for k in ["scraper", "crawl", "scrap", "spider", "download page", "fetch page"]):
        return textwrap.dedent(f"""\
            # AUTO-GENERATED: {description}
            # pip install requests beautifulsoup4

            import requests
            from bs4 import BeautifulSoup

            TARGET_URL = "https://example.com"


            def scrape(url: str) -> dict:
                headers = {{"User-Agent": "Mozilla/5.0 (auto-generated scraper)"}}
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")
                title = soup.title.string.strip() if soup.title else "N/A"
                links = [a.get("href") for a in soup.find_all("a", href=True)][:10]
                paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")][:5]
                return {{
                    "url": url,
                    "title": title,
                    "links": links,
                    "sample_text": paragraphs,
                }}


            if __name__ == "__main__":
                result = scrape(TARGET_URL)
                print(f"Title  : {{result['title']}}")
                print(f"Links  : {{result['links']}}")
                print("Sample text:")
                for p in result["sample_text"]:
                    print(f"  - {{p[:120]}}")
        """)

    # ---- database / sql / sqlite -------------------------------------
    if any(k in low for k in ["database", "db", "sql", "sqlite", "postgres", "mysql"]):
        return textwrap.dedent(f"""\
            # AUTO-GENERATED: {description}
            import sqlite3
            from datetime import datetime


            DB_FILE = "app.db"


            def init_db(conn: sqlite3.Connection) -> None:
                conn.execute(\"\"\"
                    CREATE TABLE IF NOT EXISTS records (
                        id        INTEGER PRIMARY KEY AUTOINCREMENT,
                        name      TEXT NOT NULL,
                        value     REAL,
                        created_at TEXT
                    )
                \"\"\")
                conn.commit()


            def insert(conn: sqlite3.Connection, name: str, value: float) -> int:
                cur = conn.execute(
                    "INSERT INTO records (name, value, created_at) VALUES (?, ?, ?)",
                    (name, value, datetime.now().isoformat()),
                )
                conn.commit()
                return cur.lastrowid


            def list_all(conn: sqlite3.Connection) -> list:
                return conn.execute("SELECT * FROM records ORDER BY id DESC").fetchall()


            if __name__ == "__main__":
                with sqlite3.connect(DB_FILE) as conn:
                    init_db(conn)
                    insert(conn, "item_A", 3.14)
                    insert(conn, "item_B", 2.71)
                    rows = list_all(conn)
                    print(f"Records in {{DB_FILE}}:")
                    for row in rows:
                        print(f"  {{row}}")
        """)

    # ---- telegram bot -----------------------------------------------
    if any(k in low for k in ["telegram", "bot telegram", "telebot"]):
        return textwrap.dedent(f"""\
            # AUTO-GENERATED: {description}
            # pip install requests
            import requests
            import time
            import os

            TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TOKEN_HERE")
            CHAT_ID = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "YOUR_CHAT_ID")


            def send(text: str) -> None:
                requests.post(
                    f"https://api.telegram.org/bot{{TOKEN}}/sendMessage",
                    json={{"chat_id": CHAT_ID, "text": text}},
                    timeout=10,
                )


            def get_updates(offset: int | None) -> list:
                params = {{"timeout": 20}}
                if offset:
                    params["offset"] = offset
                r = requests.get(
                    f"https://api.telegram.org/bot{{TOKEN}}/getUpdates",
                    params=params, timeout=30,
                )
                return r.json().get("result", [])


            if __name__ == "__main__":
                print("Bot starting...")
                send("Bot online!")
                offset = None
                while True:
                    for upd in get_updates(offset):
                        offset = upd["update_id"] + 1
                        text = upd.get("message", {{}}).get("text", "")
                        chat = str(upd.get("message", {{}}).get("chat", {{}}).get("id", ""))
                        if text.startswith("/"):
                            send(f"Bạn gửi: {{text}}")
                    time.sleep(1)
        """)

    # ---- default hello world / generic --------------------------------
    return textwrap.dedent(f"""\
        # AUTO-GENERATED: {description}
        import sys
        import os
        from datetime import datetime


        def main() -> None:
            print("=" * 50)
            print(f"Project  : {description}")
            print(f"Generated: {{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}}")
            print(f"Python   : {{sys.version.split()[0]}}")
            print(f"CWD      : {{os.getcwd()}}")
            print("=" * 50)
            print()
            # TODO: implement your logic here
            print("Hello from auto-generated script!")


        if __name__ == "__main__":
            main()
    """)


def _rule_based_repair(description: str, previous_code: str, error_output: str) -> str:
    """Best-effort local repair without external LLM APIs."""
    lower_err = error_output.lower()

    if "modulenotfounderror" in lower_err and "flask" in lower_err:
        return textwrap.dedent(f"""\
            # AUTO-REPAIRED: {description}
            # Flask không có sẵn -> fallback sang server chuẩn thư viện chuẩn Python.
            import json
            from http.server import BaseHTTPRequestHandler, HTTPServer


            class Handler(BaseHTTPRequestHandler):
                def _send_json(self, code: int, payload: dict) -> None:
                    body = json.dumps(payload).encode("utf-8")
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def do_GET(self):  # noqa: N802
                    if self.path == "/":
                        self._send_json(200, {{"status": "ok", "message": "Hello from repaired server"}})
                        return
                    self._send_json(404, {{"error": "not_found"}})


            if __name__ == "__main__":
                host, port = "0.0.0.0", 5000
                print(f"Starting repaired server at http://{{host}}:{{port}}")
                HTTPServer((host, port), Handler).serve_forever()
        """)

    if "modulenotfounderror" in lower_err and "bs4" in lower_err:
        return previous_code.replace("from bs4 import BeautifulSoup", "")

    if "address already in use" in lower_err or "port 5000 is in use" in lower_err:
        patched = previous_code
        patched = re.sub(r"port\s*=\s*5000", "port=5001", patched)
        patched = re.sub(r"port\s*=\s*5001", "port=5002", patched)
        patched = patched.replace("('0.0.0.0', 5000)", "('0.0.0.0', 5001)")
        patched = patched.replace("('0.0.0.0', 5001)", "('0.0.0.0', 5002)")
        patched = patched.replace("(host, port)", "(host, 5001)") if "HTTPServer((host, port)" in patched else patched
        patched = patched.replace("debug=True", "debug=False")
        if "use_reloader=False" not in patched and "app.run(" in patched:
            patched = patched.replace("debug=False)", "debug=False, use_reloader=False)")
        patched = patched.replace("http://0.0.0.0:5000", "http://0.0.0.0:5001")
        patched = patched.replace("http://0.0.0.0:5001", "http://0.0.0.0:5002")
        return patched

    return previous_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_markdown(text: str) -> str:
    """Remove ```python ... ``` fences if the LLM included them."""
    text = re.sub(r"^```[a-z]*\n?", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def slug_from_description(description: str, max_len: int = 30) -> str:
    """Turn a description string into a safe filename slug."""
    s = re.sub(r"[^\w\s]", "", description.lower())
    s = re.sub(r"\s+", "_", s.strip())
    return s[:max_len].strip("_") or "project"
