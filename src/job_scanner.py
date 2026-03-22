from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import requests


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _parse_iso_date(value: str) -> str:
    text = _safe_text(value)
    if not text:
        return "N/A"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return text[:10]


def get_searchjob_auto_scan_interval_sec() -> int:
    raw = os.getenv("SEARCHJOB_AUTO_SCAN_INTERVAL_SEC", "300").strip()
    try:
        value = int(raw)
        return max(30, value)
    except Exception:
        return 300


def search_remote_jobs(keyword: str = "", limit: int = 8) -> dict[str, Any]:
    """Search remote jobs from public source and return normalized results."""
    kw = keyword.strip().lower()

    url = "https://remotive.com/api/remote-jobs"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    payload = response.json()
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []

    normalized: list[dict[str, str]] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue

        title = _safe_text(item.get("title"))
        company = _safe_text(item.get("company_name"))
        category = _safe_text(item.get("category"))
        candidate_text = " ".join([title, company, category]).lower()

        if kw and kw not in candidate_text:
            continue

        normalized.append(
            {
                "title": title or "Unknown role",
                "company": company or "Unknown company",
                "category": category or "N/A",
                "location": _safe_text(item.get("candidate_required_location"), "Worldwide"),
                "date": _parse_iso_date(_safe_text(item.get("publication_date"))),
                "url": _safe_text(item.get("url")),
            }
        )

        if len(normalized) >= max(1, limit):
            break

    return {
        "keyword": kw,
        "count": len(normalized),
        "jobs": normalized,
    }


def format_searchjob_report(result: dict[str, Any]) -> str:
    keyword = _safe_text(result.get("keyword"))
    jobs = result.get("jobs", []) if isinstance(result, dict) else []

    lines = [
        "OpenClaw Job Search",
        f"Keyword: {keyword or 'all'}",
        f"Found: {len(jobs)}",
    ]

    if not jobs:
        lines.append("Không tìm thấy job phù hợp. Thử keyword khác, ví dụ: python, data, devops, ai")
        return "\n".join(lines)

    for idx, job in enumerate(jobs, start=1):
        lines.append(
            (
                f"{idx}) {job.get('title')} | {job.get('company')} | {job.get('location')} | {job.get('date')}"
            )
        )
        lines.append(f"   {job.get('url')}")

    lines.append("Tip: dùng /searchjob <keyword>. Ví dụ: /searchjob python")
    return "\n".join(lines)


def format_searchjob_auto_alert(keyword: str, jobs: list[dict[str, str]]) -> str:
    lines = [
        "🔎 Job auto update",
        f"Keyword: {keyword or 'all'}",
        f"New jobs: {len(jobs)}",
    ]

    for idx, job in enumerate(jobs[:5], start=1):
        lines.append(
            f"{idx}) {job.get('title')} | {job.get('company')} | {job.get('location')} | {job.get('date')}"
        )
        lines.append(f"   {job.get('url')}")

    lines.append("Dùng /searchjob stop để dừng auto scan.")
    return "\n".join(lines)


def format_verification_required_alert(job: dict[str, str]) -> str:
    title = _safe_text(job.get("title"), "Unknown role")
    company = _safe_text(job.get("company"), "Unknown company")
    url = _safe_text(job.get("url"), "")

    lines = [
        "⚠️ ACTION REQUIRED: Verify account để apply job",
        f"Role: {title}",
        f"Company: {company}",
    ]
    if url:
        lines.append(f"Link: {url}")
    lines.extend(
        [
            "Checklist thủ công:",
            "1) Mở link job và bấm Apply.",
            "2) Login/Register bằng Gmail.",
            "3) Nếu có OTP/CAPTCHA/email verify, hoàn tất rồi quay lại bot.",
            "4) Gõ /searchjob status để tiếp tục theo dõi job mới.",
        ]
    )
    return "\n".join(lines)
