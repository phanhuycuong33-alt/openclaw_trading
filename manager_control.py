# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import os
import re
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from src.binance_trader import BinanceFuturesTrader
from src.ai_coder import generate_code, generate_code_from_error, slug_from_description


load_dotenv()


def _send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=20).raise_for_status()


def _get_updates(token: str, offset: int | None, timeout: int = 25) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    payload: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        payload["offset"] = offset
    response = requests.get(url, params=payload, timeout=timeout + 10)
    response.raise_for_status()
    return response.json()


class OpenClawManager:
    def __init__(self) -> None:
        self.token = os.getenv("MANAGER_TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.allowed_chat = os.getenv(
            "MANAGER_TELEGRAM_ALLOWED_CHAT_ID",
            os.getenv("TELEGRAM_ALLOWED_CHAT_ID", ""),
        ).strip()
        self.poll_interval_sec = max(1, int(os.getenv("TELEGRAM_POLL_INTERVAL_SEC", "2")))
        self.running = True
        self.trade_proc: subprocess.Popen[str] | None = None
        self.mmo_proc: subprocess.Popen[str] | None = None
        self.build_mode = False  # AI coder mode: /start build ... /stop build
        self.offset: int | None = None
        self.host = socket.gethostname()
        self.root_dir = Path(__file__).resolve().parent
        self.last_generated_file: Path | None = None  # last file from /command
        self.last_command_description: str | None = None  # for /command retry
        self.trade_token_override = os.getenv("OPENCLAW_TELEGRAM_BOT_TOKEN", "").strip()
        self.trade_chat_override = os.getenv("OPENCLAW_TELEGRAM_ALLOWED_CHAT_ID", "").strip()
        self.mmo_token_override = os.getenv("MMO_TELEGRAM_BOT_TOKEN", "").strip()
        self.mmo_chat_override = os.getenv("MMO_TELEGRAM_ALLOWED_CHAT_ID", "").strip()
        
        # Conversational developer mode — multi-turn dialog
        self.build_conversation_state = "IDLE"  # IDLE | ASKING_TASK | CONFIRMING_TASK | BUILDING
        self.build_pending_description = ""  # temp storage for user description
        self.build_pending_details = {}  # temp storage for task details

        if not self.token:
            raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN trong .env")

    def _close_all_positions(self) -> str:
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
        if not api_key or not api_secret:
            return "Không close được vị thế: thiếu BINANCE_API_KEY/BINANCE_API_SECRET."

        try:
            trader = BinanceFuturesTrader(api_key=api_key, api_secret=api_secret, dry_run=False)
            result = trader.close_all_open_positions()
            closed = int(result.get("closed") or 0)
            requested = int(result.get("requested") or 0)
            errors = result.get("errors") or []
            message = f"Close all positions: đóng {closed}/{requested} vị thế."
            if errors:
                message += " Lỗi: " + "; ".join(str(item) for item in errors)
            return message
        except Exception as exc:
            return f"Close all positions thất bại: {exc}"

    def _is_proc_running(self, proc: subprocess.Popen[str] | None) -> bool:
        return proc is not None and proc.poll() is None

    def _is_trade_running(self) -> bool:
        return self._is_proc_running(self.trade_proc)

    def _is_mmo_running(self) -> bool:
        return self._is_proc_running(self.mmo_proc)

    def _start_bot(self, mode: str) -> str:
        if mode == "trade":
            if self._is_trade_running():
                return "Trade bot đang chạy rồi."
            token_override = self.trade_token_override
            chat_override = self.trade_chat_override
            label = "Trade"
        else:
            if self._is_mmo_running():
                return "MMO bot đang chạy rồi."
            token_override = self.mmo_token_override
            chat_override = self.mmo_chat_override
            label = "MMO"

        child_token = token_override or self.token
        if child_token == self.token:
            return (
                f"Không thể /start {mode} vì manager và bot con dùng cùng TELEGRAM token -> lỗi 409 Conflict.\n"
                "Hãy cấu hình bot riêng trong .env:\n"
                "- MANAGER_TELEGRAM_BOT_TOKEN=...\n"
                f"- {('OPENCLAW' if mode == 'trade' else 'MMO')}_TELEGRAM_BOT_TOKEN=...\n"
                "(và có thể tách chat id tương ứng)."
            )

        child_env = os.environ.copy()
        if token_override:
            child_env["TELEGRAM_BOT_TOKEN"] = token_override
        if chat_override:
            child_env["TELEGRAM_ALLOWED_CHAT_ID"] = chat_override

        proc = subprocess.Popen(
            ["./run", "openclaw", "telegram"],
            cwd=str(self.root_dir),
            env=child_env,
            stdout=None,
            stderr=None,
            text=True,
        )
        if mode == "trade":
            self.trade_proc = proc
        else:
            self.mmo_proc = proc
        return f"Đã start {label} telegram bot (pid={proc.pid})."

    def _stop_bot(self, mode: str, close_positions: bool = False) -> str:
        proc = self.trade_proc if mode == "trade" else self.mmo_proc
        label = "Trade" if mode == "trade" else "MMO"
        if not self._is_proc_running(proc):
            if mode == "trade":
                self.trade_proc = None
            else:
                self.mmo_proc = None
            return f"{label} bot hiện không chạy."

        assert proc is not None

        prefix = ""
        if close_positions:
            prefix = self._close_all_positions() + "\n"

        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=12)
            code = proc.returncode
            if mode == "trade":
                self.trade_proc = None
            else:
                self.mmo_proc = None
            return f"{prefix}Đã stop {label} telegram bot (exit={code})."
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            code = proc.returncode
            if mode == "trade":
                self.trade_proc = None
            else:
                self.mmo_proc = None
            return f"{prefix}Đã force terminate {label} telegram bot (exit={code})."

    # ------------------------------------------------------------------
    # AI code generator  (/command ... /run /code)
    # ------------------------------------------------------------------

    def _execute_file(self, file_path: Path, timeout_sec: int = 60) -> tuple[int, str, str, bool]:
        cmd = [sys.executable, str(file_path)] if file_path.suffix == ".py" else ["bash", str(file_path)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                cwd=str(self.root_dir),
            )
            return proc.returncode, proc.stdout.strip(), proc.stderr.strip(), False
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "").strip() if isinstance(exc.stdout, str) else ""
            err = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
            return 124, out, err or f"Timeout sau {timeout_sec} giây", True
        except Exception as exc:
            return 1, "", str(exc), False

    def _extract_missing_module(self, error_output: str) -> str | None:
        m = re.search(r"No module named ['\"]([^'\"]+)['\"]", error_output)
        if not m:
            return None
        return m.group(1).strip()

    def _is_expected_long_running(self, description: str, out: str, err: str) -> bool:
        low_desc = description.lower()
        low_out = (out or "").lower()
        low_err = (err or "").lower()
        app_like = any(k in low_desc for k in ["website", "web", "server", "flask", "api"])
        if app_like:
            # Các app web/server thường chạy liên tục; timeout khi run test là bình thường.
            return True
        started_hint = any(
            k in (low_out + "\n" + low_err)
            for k in ["starting server", "running on", "serving", "http://", "0.0.0.0"]
        )
        return app_like and started_hint

    def _auto_install_missing_module(self, module_name: str) -> tuple[bool, str]:
        package_map = {
            "flask": "flask",
            "bs4": "beautifulsoup4",
            "pandas": "pandas",
            "numpy": "numpy",
            "requests": "requests",
            "ta": "ta",
        }
        package_name = package_map.get(module_name)
        if not package_name:
            return False, f"Không có mapping package cho module '{module_name}'."

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", package_name],
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(self.root_dir),
            )
            if proc.returncode == 0:
                return True, f"Đã cài package '{package_name}' cho module '{module_name}'."
            combined = (proc.stdout + "\n" + proc.stderr).strip()
            return False, f"Cài package '{package_name}' thất bại: {combined[:400]}"
        except Exception as exc:
            return False, f"Lỗi cài package '{package_name}': {exc}"

    def _auto_retry_until_success(self) -> str:
        if self.last_generated_file is None or not self.last_generated_file.exists():
            return "Chưa có file để retry. Dùng /command 'mô tả' trước."
        if not self.last_command_description:
            return "Chưa có description trước đó để retry. Dùng /command 'mô tả' trước."

        max_attempts = max(1, int(os.getenv("BUILD_RETRY_MAX_ATTEMPTS", "3")))
        description = self.last_command_description
        current_file = self.last_generated_file
        logs: list[str] = []

        for attempt in range(1, max_attempts + 1):
            code, out, err, timed_out = self._execute_file(current_file, timeout_sec=60)
            if code == 0:
                output = out or "(no stdout)"
                logs.append(f"Attempt {attempt}: ✅ chạy thành công {current_file.name}")
                return (
                    "✅ Auto-retry thành công.\n"
                    f"File: {current_file.name}\n"
                    + "\n".join(logs)
                    + f"\n\nOutput:\n{output[:1500]}"
                )

            if timed_out and self._is_expected_long_running(description, out, err):
                logs.append(f"Attempt {attempt}: ✅ app chạy dạng long-running ({current_file.name})")
                output = out or err or "Server started (timeout expected for long-running app)."
                return (
                    "✅ Auto-retry thành công (server đã khởi động, timeout là bình thường).\n"
                    f"File: {current_file.name}\n"
                    + "\n".join(logs)
                    + f"\n\nOutput:\n{output[:1500]}"
                )

            runtime_error = err or out or "Unknown runtime error"
            logs.append(f"Attempt {attempt}: ❌ {current_file.name} exit={code}")

            if timed_out:
                logs.append("  - Lỗi timeout, sẽ thử sửa code để giảm tác vụ dài.")

            missing_module = self._extract_missing_module(runtime_error)
            if missing_module:
                ok_install, install_msg = self._auto_install_missing_module(missing_module)
                logs.append(f"  - {install_msg}")
                if ok_install:
                    rerun_code, rerun_out, rerun_err, _ = self._execute_file(current_file, timeout_sec=60)
                    if rerun_code == 0:
                        output = rerun_out or "(no stdout)"
                        logs.append("  - ✅ Sau khi cài package, script chạy OK.")
                        return (
                            "✅ Auto-retry thành công (fix bằng auto-install package).\n"
                            f"File: {current_file.name}\n"
                            + "\n".join(logs)
                            + f"\n\nOutput:\n{output[:1500]}"
                        )
                    runtime_error = rerun_err or rerun_out or runtime_error

            try:
                previous_code = current_file.read_text(encoding="utf-8")
            except Exception:
                previous_code = ""

            fixed_code, engine = generate_code_from_error(description, previous_code, runtime_error)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = slug_from_description(description)
            fixed_file = self.root_dir / f"gen_{ts}_{slug}_fix{attempt}.py"
            fixed_file.write_text(fixed_code, encoding="utf-8")
            self.last_generated_file = fixed_file
            current_file = fixed_file
            logs.append(f"  - Đã sinh bản sửa bằng [{engine}] -> {fixed_file.name}")

        return (
            "❌ Auto-retry chưa sửa được hoàn toàn sau tối đa số lần thử.\n"
            f"File cuối: {self.last_generated_file.name if self.last_generated_file else '(none)'}\n"
            + "\n".join(logs)
            + "\n\nGợi ý: dùng /code để xem code hiện tại rồi /command mô tả rõ hơn."
        )

    def _handle_build_conversation(self, text: str) -> tuple[str, bool] | None:
        """Handle multi-turn conversation during build mode.
        Returns (reply, continue_running) if handled, else None.
        
        States:
        - ASKING_TASK: waits for user to describe what they want
        - CONFIRMING_TASK: waits for user confirmation before generating
        """
        if self.build_conversation_state == "IDLE":
            return None
        
        stripped = text.strip().lower()
        
        # ASKING_TASK: user describes what they want
        if self.build_conversation_state == "ASKING_TASK":
            if not text.strip():
                return "Vui lòng nhập mô tả công việc bạn muốn làm.", False
            
            self.build_pending_description = text.strip()
            
            # Determine task type and ask for details
            task_type = self._infer_task_type(self.build_pending_description)
            
            if task_type == "web":
                detail_msg = (
                    f"📝 Bạn muốn tạo: **{self.build_pending_description}**\n\n"
                    "Bạn muốn:\n"
                    "• web nào? (web đơn giản, API server, webapp có database, ...)\n"
                    "• cần tính năng gì? (login, upload file, real-time, ...)\n\n"
                    "Gõ 'ok' để bắt đầu build ngay, hoặc thêm chi tiết."
                )
            elif task_type == "script":
                detail_msg = (
                    f"📝 Script: **{self.build_pending_description}**\n\n"
                    "Chi tiết:\n"
                    "• Input/output gì?\n"
                    "• Các thư viện cần?\n\n"
                    "Gõ 'ok' để bắt đầu, hoặc nói thêm chi tiết."
                )
            elif task_type == "api":
                detail_msg = (
                    f"📝 API: **{self.build_pending_description}**\n\n"
                    "Bạn cần:\n"
                    "• Endpoint nào?\n"
                    "• Kiểu database nào?\n"
                    "• Authentication?\n\n"
                    "Gõ 'ok' để bắt đầu."
                )
            else:
                detail_msg = (
                    f"📝 Task: **{self.build_pending_description}**\n\n"
                    "Gõ 'ok' để bắt đầu build ngay."
                )
            
            self.build_conversation_state = "CONFIRMING_TASK"
            return detail_msg, False
        
        # CONFIRMING_TASK: wait for ok/confirm or more details
        if self.build_conversation_state == "CONFIRMING_TASK":
            if stripped in {"ok", "yes", "yep", "chạy", "được", "ok được", "start"}:
                # User confirmed — start building
                self.build_conversation_state = "BUILDING"
                return self._start_build_task(), False
            elif stripped == "cancel" or stripped.startswith("/stop"):
                # User cancelled
                self.build_conversation_state = "IDLE"
                return "Build cancelled. Gõ /start build để bắt đầu lại.", False
            else:
                # User adding more details
                self.build_pending_description += "\n" + text.strip()
                return (
                    f"💬 Ghi nhận thêm: \"{text.strip()}\"\n"
                    f"Mô tả hiện tại: {self.build_pending_description}\n\n"
                    "Gõ 'ok' để bắt đầu build."
                ), False
        
        return None
    
    def _infer_task_type(self, description: str) -> str:
        """Guess task type from description."""
        lower = description.lower()
        if any(k in lower for k in ["web", "website", "flask", "django", "html", "frontend"]):
            return "web"
        if any(k in lower for k in ["api", "server", "endpoint", "rest"]):
            return "api"
        if any(k in lower for k in ["script", "tool", "scraper", "bot"]):
            return "script"
        return "generic"
    
    def _start_build_task(self) -> tuple[str, bool]:
        """Generate code for the pending task."""
        description = self.build_pending_description
        if not description:
            return "Không có mô tả. Hãy /start build lại.", False
        
        # Generate code
        try:
            _send_message(self.token, self.allowed_chat, "Dang tao code... vui long cho")
        except:
            pass
        
        code, engine = generate_code(description)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = slug_from_description(description)
        gen_file = self.root_dir / f"gen_{ts}_{slug}.py"
        gen_file.write_text(code, encoding="utf-8")
        self.last_generated_file = gen_file
        self.last_command_description = description
        
        # Run it
        cmd = [sys.executable, str(gen_file)]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60, cwd=str(self.root_dir)
            )
            out = proc.stdout.strip() or "(no output)"
            err = proc.stderr.strip() or ""
            
            # Report success/error
            if proc.returncode == 0:
                output_summary = out[:500] if len(out) < 500 else out[:500] + "..."
                self.build_conversation_state = "IDLE"
                return (
                    f"✅ Build thành công!\n\n"
                    f"📄 File: {gen_file.name}\n"
                    f"🔧 Engine: [{engine}]\n"
                    f"✨ Output:\n{output_summary}\n\n"
                    f"Dùng /code để xem source, /run để chạy lại, /retry để sửa lỗi.\n"
                    f"Gõ /stop build để tắt build mode."
                ), False
            else:
                # Error
                error_msg = err or out or "Unknown error"
                self.build_conversation_state = "IDLE"
                return (
                    f"❌ Build có lỗi:\n\n{error_msg[:800]}\n\n"
                    f"Dùng /retry để tự động sửa, hoặc /start build lại."
                ), False
        except subprocess.TimeoutExpired:
            # Long-running app (web server) — timeout is expected
            if self._is_expected_long_running(description, "", ""):
                self.build_conversation_state = "IDLE"
                port_hint = "5000" if "5000" in code else "3000"
                return (
                    f"✅ Build thành công - Server đã chạy!\n\n"
                    f"📄 File: {gen_file.name}\n"
                    f"🔧 Engine: [{engine}]\n"
                    f"🌐 Truy cập: http://localhost:{port_hint} hoặc xem terminal.\n\n"
                    f"Dùng /code để xem source, /stop build để dừng."
                ), False
            else:
                self.build_conversation_state = "IDLE"
                return (
                    f"⏱️ Build timeout sau 60 giây.\n\n"
                    f"📄 File: {gen_file.name}\n"
                    f"Dùng /retry để tự động sửa, hoặc /code để xem source."
                ), False
        except Exception as exc:
            self.build_conversation_state = "IDLE"
            return f"❌ Lỗi khi build: {exc}", False

    def _handle_codegen(self, text: str) -> str | None:
        """Handle /command '<description>' or /retry — generate + save Python code via AI.
        - /command 'desc' → generate from desc
        - /command retry → regenerate from last description
        - /retry → same as /command retry
        Returns reply string, or None if text doesn't match patterns.
        """
        stripped = text.strip()
        
        # Check if it's /retry or /command
        is_retry = re.match(r"(?i)^/retry\b", stripped)
        is_command = re.match(r"(?i)^/command\b", stripped)
        
        if not is_retry and not is_command:
            return None
        
        # Extract description
        if is_retry:
            # /retry → use last description
            if self.last_command_description is None:
                return "Không có description trước đó để retry. Dùng /command 'mô tả' trước."
            description = self.last_command_description
        else:
            # /command <text>
            rest = re.sub(r"(?i)^/command\s*", "", stripped).strip()
            description = rest.strip("'\"")
            
            # Check for /command retry
            if description.lower() == "retry":
                if self.last_command_description is None:
                    return "Không có description trước đó để retry. Dùng /command 'mô tả' trước."
                description = self.last_command_description
            elif not description:
                return (
                    "Cú pháp: /command 'mô tả dự án'\n"
                    "         /command retry (tự chạy + tự sửa đến khi ổn hơn)\n"
                    "         /retry (shortcut auto-fix)\n"
                    "Ví dụ  : /command 'viết script trade coin dùng Binance API'"
                )
        
        # Generate code
        slug = slug_from_description(description)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"gen_{ts}_{slug}.py"
        out_path = self.root_dir / filename
        
        try:
            code, engine = generate_code(description)
        except Exception as exc:
            return f"Lỗi khi sinh code: {exc}"
        
        # Save file and description
        out_path.write_text(code, encoding="utf-8")
        self.last_generated_file = out_path
        self.last_command_description = description
        
        # Show preview
        lines_code = code.splitlines()
        preview_lines = lines_code[:25]
        preview = "\n".join(preview_lines)
        if len(lines_code) > 25:
            preview += f"\n... (+{len(lines_code)-25} dòng nữa)"
        
        return (
            f"✅ [{engine}] Đã tạo: {filename}\n"
            f"Mô tả: {description}\n\n"
            f"--- Preview ---\n"
            f"{preview}\n\n"
            f"Dùng /run để chạy | /code để xem toàn bộ | /retry để auto-fix"
        )

    # ------------------------------------------------------------------
    # Natural-language shell task handler
    # ------------------------------------------------------------------

    def _handle_shell_task(self, text: str) -> str | None:
        """Parse natural-language commands, run them on the server, return output.
        Returns None if the text doesn't match any recognised pattern.
        Supported:
          - 'tao/tạo/create script <name>'  → write + run a Python hello-world script
          - 'down/clone/download repo <kw>' → GitHub search + git clone top result
          - 'run/chay/chạy <filename>'      → execute an existing script/file
        """
        lower = text.lower()

        # ---- create / tạo script -----------------------------------------------
        if re.search(r"(tao|t[aạ]o|create|make).{0,20}script", lower):
            m = re.search(r"['\"](.*?)['\"]", text)
            raw_name = m.group(1) if m else "hello_world"
            safe_name = re.sub(r"[^\w\-. ]", "_", raw_name).strip().replace(" ", "_")
            if not safe_name.endswith(".py"):
                safe_name += ".py"
            script_path = self.root_dir / safe_name
            script_path.write_text(
                textwrap.dedent(f"""\
                    # auto-generated by manager bot
                    print("Hello World - {raw_name}")
                    """)
            )
            try:
                proc = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True, text=True, timeout=30,
                )
                out = proc.stdout.strip() or "(no stdout)"
                err = f"\nStderr: {proc.stderr.strip()}" if proc.stderr.strip() else ""
                return f"Đã tạo {safe_name} và chạy:\nOutput: {out}{err}"
            except Exception as exc:
                return f"Đã tạo {safe_name} nhưng chạy thất bại: {exc}"

        # ---- down / clone repo --------------------------------------------------
        if re.search(r"(down|clone|download|t[aả]i).{0,20}(repo|github)", lower):
            m = re.search(r"['\"](.*?)['\"]", text)
            kw = m.group(1) if m else re.split(r"\s+", text.strip())[-1]
            try:
                resp = requests.get(
                    "https://api.github.com/search/repositories",
                    params={"q": kw, "sort": "stars", "per_page": 1},
                    headers={"Accept": "application/vnd.github+json"},
                    timeout=15,
                )
                resp.raise_for_status()
                items = resp.json().get("items", [])
                if not items:
                    return f"Không tìm thấy repo nào trên GitHub với keyword '{kw}'."
                repo = items[0]
                clone_url = repo["clone_url"]
                repo_name = repo["name"]
                stars = repo["stargazers_count"]
                clone_dir = self.root_dir / repo_name
                if clone_dir.exists():
                    return (
                        f"Repo '{repo_name}' đã tồn tại tại {clone_dir.name}/\n"
                        f"URL: {repo['html_url']} (⭐{stars})"
                    )
                result = subprocess.run(
                    ["git", "clone", "--depth=1", clone_url, str(clone_dir)],
                    capture_output=True, text=True, timeout=120,
                )
                combined = (result.stdout + result.stderr).strip()
                if result.returncode == 0:
                    return (
                        f"Đã clone: {repo['full_name']} (⭐{stars})\n"
                        f"URL: {repo['html_url']}\n"
                        f"Thư mục: {clone_dir.name}/"
                    )
                else:
                    return f"Clone thất bại (exit {result.returncode}):\n{combined[:800]}"
            except Exception as exc:
                return f"Lỗi khi tìm/clone repo: {exc}"

        # ---- run / chạy existing script ----------------------------------------
        if re.search(r"(run|chay|ch[aạ]y|execute|exec).{0,30}['\"]", lower):
            m = re.search(r"['\"](.*?)['\"]", text)
            if m:
                target = m.group(1).strip()
                script_path = self.root_dir / target
                if not script_path.exists():
                    # try with .py
                    script_path = self.root_dir / (target + ".py")
                if not script_path.exists():
                    return f"Không tìm thấy file '{target}' trong {self.root_dir}."
                suffix = script_path.suffix
                cmd = [sys.executable, str(script_path)] if suffix == ".py" else ["bash", str(script_path)]
                try:
                    proc = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=60,
                        cwd=str(self.root_dir),
                    )
                    out = proc.stdout.strip() or "(no stdout)"
                    err = f"\nStderr: {proc.stderr.strip()}" if proc.stderr.strip() else ""
                    return f"Run '{script_path.name}' (exit {proc.returncode}):\n{out[:1200]}{err}"
                except subprocess.TimeoutExpired:
                    return f"Script '{script_path.name}' timeout sau 60 giây."
                except Exception as exc:
                    return f"Lỗi khi chạy '{script_path.name}': {exc}"

        return None

    # ------------------------------------------------------------------

    def _handle_command(self, text: str) -> tuple[str, bool]:
        command = text.strip().lower()

        if command in {"/help", "/start manager", "/manager"}:
            build_indicator = "✓ ON" if self.build_mode else "(off)"
            return (
                "Manager commands:\n"
                "/start trade   → chạy trade telegram bot\n"
                "/start mmo     → chạy mmo telegram bot\n"
                "/start build   → bật AI coder + Developer mode (hỏi công việc)\n"
                "/stop trade    → stop trade bot (kèm close all)\n"
                "/stop mmo      → stop mmo bot\n"
                "/stop build    → tắt build mode\n"
                "/stop force    → stop tất cả + dừng manager\n"
                "/status        → trạng thái processes\n"
                f"\n🤖 AI Coder mode [{build_indicator}] — Developer Bot (interactive):\n"
                "  /start build           → Bot hỏi: 'Bạn muốn làm gì?'\n"
                "  [gõ mô tả]             → Bot xác nhận + hỏi chi tiết\n"
                "  ok / yes               → Bot build ngay, xem kết quả\n"
                "  \n  Hoặc dùng truyền thống:\n"
                "  /command 'viết script' → AI sinh code (không hỏi gì cả)\n"
                "  /retry                 → Auto-fix lỗi + tự chạy\n"
                "  /run                   → Chạy file, trả stdout\n"
                "  /code                  → Xem full source\n"
                "\n🛠️ Shell tasks (viết tự nhiên):\n"
                "  tao script 'hello'     → tạo + chạy Python script\n"
                "  down repo 'keyword'    → clone GitHub\n"
                "  run 'file.py'          → chạy file có sẵn"
            ), False

        if command in {"/start", "/start trade"}:
            return self._start_bot("trade"), False

        if command == "/start mmo":
            return self._start_bot("mmo"), False

        if command == "/start build":
            if self.build_mode:
                return "Build mode đang bật rồi. Gõ /stop build để tắt.", False
            self.build_mode = True
            self.build_conversation_state = "ASKING_TASK"
            self.build_pending_description = ""
            return (
                "✅ Build mode ON — Developer mode active\n\n"
                "🤖 Bạn muốn làm gì? (ví dụ: 'tôi làm 1 web đơn giản' hay 'script lấy data từ API')\n\n"
                "Dùng /stop build để tắt build mode."
            ), False

        if command == "/stop build":
            if not self.build_mode:
                return "Build mode không bật.", False
            self.build_mode = False
            return "Build mode OFF.", False

        if command in {"/stop", "/stop trade"}:
            return self._stop_bot("trade", close_positions=True), False

        if command == "/stop mmo":
            return self._stop_bot("mmo", close_positions=False), False

        if command == "/stop force":
            stop_trade = self._stop_bot("trade", close_positions=True)
            stop_mmo = self._stop_bot("mmo", close_positions=False)
            self.build_mode = False
            self.running = False
            return f"{stop_trade}\n{stop_mmo}\nBuild mode OFF.\nManager sẽ dừng ngay.", True

        if command == "/status":
            trade_state = "RUNNING" if self._is_trade_running() else "STOPPED"
            mmo_state = "RUNNING" if self._is_mmo_running() else "STOPPED"
            build_state = "ON" if self.build_mode else "OFF"
            trade_pid = self.trade_proc.pid if self._is_trade_running() and self.trade_proc else "-"
            mmo_pid = self.mmo_proc.pid if self._is_mmo_running() and self.mmo_proc else "-"
            gen_file = self.last_generated_file.name if self.last_generated_file else "(none)"
            return (
                "Manager: RUNNING\n"
                f"Trade telegram: {trade_state} | PID: {trade_pid}\n"
                f"MMO telegram: {mmo_state} | PID: {mmo_pid}\n"
                f"Build mode: {build_state}\n"
                f"Last generated: {gen_file}"
            ), False

        if command == "/retry" or re.match(r"(?i)^/command\s+retry\s*$", text.strip()):
            if not self.build_mode:
                return "❌ Build mode OFF. Dùng /start build trước.", False
            return self._auto_retry_until_success(), False

        # AI code generator: /command '<description>'
        codegen_result = self._handle_codegen(text)
        if codegen_result is not None:
            if not self.build_mode:
                return "❌ Build mode OFF. Dùng /start build trước.", False
            return codegen_result, False

        # /run — execute last generated file
        if command == "/run":
            if not self.build_mode:
                return "❌ Build mode OFF. Dùng /start build trước.", False
            if self.last_generated_file is None or not self.last_generated_file.exists():
                return "Chưa có file nào được tạo. Dùng /command 'mô tả' trước.", False
            fp = self.last_generated_file
            cmd = [sys.executable, str(fp)] if fp.suffix == ".py" else ["bash", str(fp)]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60,
                    cwd=str(self.root_dir),
                )
                out = proc.stdout.strip() or "(no stdout)"
                err = f"\nStderr: {proc.stderr.strip()[:400]}" if proc.stderr.strip() else ""
                return f"Run '{fp.name}' (exit {proc.returncode}):\n{out[:1500]}{err}", False
            except subprocess.TimeoutExpired:
                return f"Script '{fp.name}' timeout sau 60 giây.", False
            except Exception as exc:
                return f"Lỗi khi chạy '{fp.name}': {exc}", False

        # /code — show full source
        if command == "/code":
            if not self.build_mode:
                return "❌ Build mode OFF. Dùng /start build trước.", False
            if self.last_generated_file is None or not self.last_generated_file.exists():
                return "Chưa có file nào được tạo. Dùng /command 'mô tả' trước.", False
            fp = self.last_generated_file
            src = fp.read_text(encoding="utf-8")
            # Telegram message limit 4096 chars
            if len(src) > 3800:
                src = src[:3800] + f"\n... (truncated, full file: {fp.name})"
            return f"--- {fp.name} ---\n{src}", False

        # Natural-language shell task fallback
        shell_result = self._handle_shell_task(text)
        if shell_result is not None:
            return shell_result, False

        # Check if in build conversation mode (multi-turn dialog)
        if self.build_mode and self.build_conversation_state != "IDLE":
            conv_result = self._handle_build_conversation(text)
            if conv_result is not None:
                return conv_result

        return "Lệnh không hợp lệ. Dùng /help để xem lệnh.\nHoặc viết tự nhiên vd: 'tao script hello world' / 'down repo trade coin' / 'run myscript'", False

    def _poll_children_health(self) -> list[str]:
        messages: list[str] = []
        if self.trade_proc is not None:
            code = self.trade_proc.poll()
            if code is not None:
                self.trade_proc = None
                messages.append(f"Trade telegram bot đã dừng (exit={code}).")
        if self.mmo_proc is not None:
            code = self.mmo_proc.poll()
            if code is not None:
                self.mmo_proc = None
                messages.append(f"MMO telegram bot đã dừng (exit={code}).")
        return messages

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._shutdown_signal)
        signal.signal(signal.SIGTERM, self._shutdown_signal)

        print("Manager đang chạy... chờ lệnh Telegram /start trade|mmo /stop trade|mmo", flush=True)

        if self.allowed_chat:
            try:
                token_note = ""
                if not self.trade_token_override:
                    token_note = (
                        "\nLưu ý: manager và bot con đang dùng chung TELEGRAM_BOT_TOKEN. "
                        "Nên cấu hình MANAGER_TELEGRAM_BOT_TOKEN + OPENCLAW_TELEGRAM_BOT_TOKEN + MMO_TELEGRAM_BOT_TOKEN để ổn định."
                    )
                _send_message(
                    self.token,
                    self.allowed_chat,
                    (
                        f"Manager online trên {self.host}.\n"
                        "Gửi /start trade hoặc /start mmo để chạy bot con."
                        f"{token_note}"
                    ),
                )
            except Exception:
                pass

        try:
            latest = _get_updates(self.token, offset=None, timeout=1)
            results = latest.get("result", [])
            if results:
                self.offset = results[-1].get("update_id", 0) + 1
        except Exception:
            self.offset = None

        while self.running:
            for child_msg in self._poll_children_health():
                if self.allowed_chat:
                    try:
                        _send_message(self.token, self.allowed_chat, child_msg)
                    except Exception:
                        pass

            try:
                payload = _get_updates(self.token, offset=self.offset)
                results = payload.get("result", [])

                for update in results:
                    self.offset = update.get("update_id", 0) + 1
                    msg = update.get("message", {})
                    text = str(msg.get("text") or "").strip()
                    chat_id = str(msg.get("chat", {}).get("id", ""))

                    if not text:
                        continue

                    if self.allowed_chat and chat_id != self.allowed_chat:
                        _send_message(self.token, chat_id, "Unauthorized chat id")
                        continue

                    reply, should_stop_manager = self._handle_command(text)
                    _send_message(self.token, chat_id, reply)
                    if should_stop_manager:
                        break
            except KeyboardInterrupt:
                self.running = False
            except Exception as exc:
                print(f"Manager loop error: {exc}", flush=True)
                time.sleep(self.poll_interval_sec)

        if self._is_trade_running():
            self._stop_bot("trade", close_positions=True)
        if self._is_mmo_running():
            self._stop_bot("mmo", close_positions=False)

        if self.allowed_chat:
            try:
                _send_message(self.token, self.allowed_chat, f"Manager offline trên {self.host}.")
            except Exception:
                pass

    def _shutdown_signal(self, signum: int, _frame: Any) -> None:
        self.running = False
        print(f"Nhận signal {signum}, đang tắt manager...", flush=True)


if __name__ == "__main__":
    OpenClawManager().run()
