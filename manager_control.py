from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


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
        self.child_proc: subprocess.Popen[str] | None = None
        self.offset: int | None = None
        self.host = socket.gethostname()
        self.root_dir = Path(__file__).resolve().parent
        self.child_token_override = os.getenv("OPENCLAW_TELEGRAM_BOT_TOKEN", "").strip()
        self.child_chat_override = os.getenv("OPENCLAW_TELEGRAM_ALLOWED_CHAT_ID", "").strip()

        if not self.token:
            raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN trong .env")

    def _is_child_running(self) -> bool:
        return self.child_proc is not None and self.child_proc.poll() is None

    def _start_child(self) -> str:
        if self._is_child_running():
            return "OpenClaw telegram bot đang chạy rồi."

        child_token = self.child_token_override or self.token
        if child_token == self.token:
            return (
                "Không thể /start vì manager và bot con đang dùng cùng TELEGRAM token -> gây lỗi 409 Conflict.\n"
                "Hãy cấu hình 2 bot riêng trong .env:\n"
                "- MANAGER_TELEGRAM_BOT_TOKEN=...\n"
                "- OPENCLAW_TELEGRAM_BOT_TOKEN=...\n"
                "(và có thể tách chat id tương ứng)."
            )

        child_env = os.environ.copy()
        if self.child_token_override:
            child_env["TELEGRAM_BOT_TOKEN"] = self.child_token_override
        if self.child_chat_override:
            child_env["TELEGRAM_ALLOWED_CHAT_ID"] = self.child_chat_override

        self.child_proc = subprocess.Popen(
            ["./run", "openclaw", "telegram"],
            cwd=str(self.root_dir),
            env=child_env,
            stdout=None,
            stderr=None,
            text=True,
        )
        return f"Đã start OpenClaw telegram bot (pid={self.child_proc.pid})."

    def _stop_child(self) -> str:
        if not self._is_child_running():
            self.child_proc = None
            return "OpenClaw telegram bot hiện không chạy."

        assert self.child_proc is not None

        try:
            self.child_proc.send_signal(signal.SIGINT)
            self.child_proc.wait(timeout=12)
            code = self.child_proc.returncode
            self.child_proc = None
            return f"Đã stop OpenClaw telegram bot (exit={code})."
        except subprocess.TimeoutExpired:
            self.child_proc.terminate()
            try:
                self.child_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child_proc.kill()
                self.child_proc.wait(timeout=5)
            code = self.child_proc.returncode
            self.child_proc = None
            return f"Đã force terminate OpenClaw telegram bot (exit={code})."

    def _handle_command(self, text: str) -> tuple[str, bool]:
        command = text.strip().lower()

        if command in {"/help", "/start manager", "/manager"}:
            return (
                "Manager commands:\n"
                "/start -> chạy ./run openclaw telegram\n"
                "/stop -> stop ./run openclaw telegram (manager vẫn chạy)\n"
                "/stop force -> stop bot và stop luôn manager\n"
                "/status -> trạng thái manager/process"
            ), False

        if command == "/start":
            return self._start_child(), False

        if command == "/stop":
            return self._stop_child(), False

        if command == "/stop force":
            stop_msg = self._stop_child()
            self.running = False
            return f"{stop_msg}\nManager sẽ dừng ngay.", True

        if command == "/status":
            state = "RUNNING" if self._is_child_running() else "STOPPED"
            pid = self.child_proc.pid if self._is_child_running() and self.child_proc else "-"
            return f"Manager: RUNNING\nOpenClaw telegram: {state}\nPID: {pid}", False

        return "Lệnh không hợp lệ. Dùng /help để xem lệnh manager.", False

    def _poll_child_health(self) -> str | None:
        if self.child_proc is None:
            return None
        code = self.child_proc.poll()
        if code is None:
            return None
        self.child_proc = None
        return f"OpenClaw telegram bot đã dừng (exit={code})."

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._shutdown_signal)
        signal.signal(signal.SIGTERM, self._shutdown_signal)

        print("Manager đang chạy... chờ lệnh Telegram /start /stop /stop force", flush=True)

        if self.allowed_chat:
            try:
                token_note = ""
                if not self.child_token_override:
                    token_note = (
                        "\nLưu ý: manager và bot con đang dùng chung TELEGRAM_BOT_TOKEN. "
                        "Nên cấu hình MANAGER_TELEGRAM_BOT_TOKEN + OPENCLAW_TELEGRAM_BOT_TOKEN để ổn định."
                    )
                _send_message(
                    self.token,
                    self.allowed_chat,
                    (
                        f"Manager online trên {self.host}.\n"
                        "Gửi /start để chạy OpenClaw telegram bot."
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
            child_msg = self._poll_child_health()
            if child_msg and self.allowed_chat:
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

        if self._is_child_running():
            self._stop_child()

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
