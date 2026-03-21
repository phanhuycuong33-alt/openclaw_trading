from __future__ import annotations

import os
from typing import Any

import requests


MMO_PROJECTS: list[dict[str, Any]] = [
    {
        "name": "changedetection.io",
        "repo": "dgtlmoon/changedetection.io",
        "category": "deal monitoring / affiliate alerts",
        "how": "Theo dõi giá sản phẩm, trang flash sale, vé rẻ; gửi alert Telegram và gắn affiliate link hoặc bán membership deal alerts.",
        "budget": "thấp",
        "difficulty": "thấp",
        "risk": "thấp",
        "fit": "Rất hợp cho solo operator, chỉ cần VPS nhỏ và list URL theo dõi.",
    },
    {
        "name": "n8n",
        "repo": "n8n-io/n8n",
        "category": "automation / lead generation",
        "how": "Tự động crawl form leads, gửi email, đẩy CRM, nuôi affiliate funnel hoặc bán dịch vụ automation cho khách.",
        "budget": "thấp",
        "difficulty": "trung bình",
        "risk": "thấp",
        "fit": "Hợp nếu muốn kiếm tiền từ automation service hoặc funnel data.",
    },
    {
        "name": "Ghost",
        "repo": "TryGhost/Ghost",
        "category": "newsletter / content subscription",
        "how": "Chạy blog hoặc newsletter trả phí, SEO content, affiliate content, sponsor post.",
        "budget": "thấp",
        "difficulty": "trung bình",
        "risk": "thấp",
        "fit": "An toàn và bền vững hơn kiểu MMO ngắn hạn; cần content đều.",
    },
    {
        "name": "Huginn",
        "repo": "huginn/huginn",
        "category": "agents / content and signal automation",
        "how": "Tạo agents theo dõi web, nguồn tin, keyword; bán tín hiệu, nội dung tổng hợp, hoặc nội dung affiliate.",
        "budget": "thấp",
        "difficulty": "trung bình",
        "risk": "thấp",
        "fit": "Tốt nếu bạn muốn nhiều bots nhỏ chạy trên server.",
    },
    {
        "name": "Mautic",
        "repo": "mautic/mautic",
        "category": "marketing funnel / email monetization",
        "how": "Tạo landing page, email sequences, lead capture và nuôi khách cho affiliate hoặc sản phẩm số.",
        "budget": "trung bình",
        "difficulty": "trung bình",
        "risk": "thấp",
        "fit": "Phù hợp khi đã có traffic hoặc data từ ads/SEO/form.",
    },
    {
        "name": "Chatwoot",
        "repo": "chatwoot/chatwoot",
        "category": "support SaaS / client service",
        "how": "Dùng làm nền tảng chăm sóc khách cho shop nhỏ, agency hoặc dịch vụ local và thu phí vận hành hằng tháng.",
        "budget": "trung bình",
        "difficulty": "trung bình",
        "risk": "thấp",
        "fit": "Không phải tiền tự chảy vào, nhưng rất thực tế nếu bán dịch vụ B2B nhỏ.",
    },
]


TOP_SAFE = ["changedetection.io", "n8n", "Ghost"]

AUTO_NICHE = {
    "name": "AI tools + SaaS deals + hosting/VPS offers",
    "why": (
        "Phù hợp nhất khi bạn chạy trên Google server: sản phẩm số, không cần giao hàng, "
        "dễ gắn affiliate, dễ theo dõi thay đổi giá/trial/coupon, và audience online rõ ràng."
    ),
    "keywords": [
        "ai tool deal",
        "lifetime deal ai",
        "vps coupon",
        "hosting deal",
        "cloud credits",
        "domain promo",
        "proxy discount",
        "seo tool discount",
        "email marketing deal",
        "chatbot discount",
    ],
    "sources": [
        "pricing pages của SaaS",
        "lifetime deal pages",
        "hosting/VPS promo pages",
        "domain registrar promo pages",
        "AppSumo / deal blogs / launch pages",
    ],
}


def get_mmo_report() -> str:
    best = MMO_PROJECTS[0]
    lines = [
        "MMO mode: bot tự chọn 1 hướng khả thi nhất",
        "Tôi KHÔNG chọn kiểu click ads / survey farm vì thu nhập thấp, dễ khóa tài khoản, và dễ vi phạm nền tảng.",
        "",
        f"Phương án được chọn: {best['name']}",
        f"Repo: {best['repo']}",
        f"Mô hình: {best['category']}",
        f"Kiếm tiền: {best['how']}",
        "",
        "Vì sao chọn phương án này:",
        "- Dễ chạy trên VPS nhỏ",
        "- Có thể nối thẳng Telegram để bắn deal",
        "- Có thể kiếm tiền qua affiliate hoặc nhóm premium",
        "- Không cần hành vi rủi ro như click ads hay survey hàng loạt",
        "",
        f"Niche bot tự chọn: {AUTO_NICHE['name']}",
        f"Lý do: {AUTO_NICHE['why']}",
        "",
        "Keyword bot tự chọn:",
    ]

    for keyword in AUTO_NICHE["keywords"]:
        lines.append(f"- {keyword}")

    lines.extend([
        "",
        "Nguồn nên theo dõi:",
    ])

    for source in AUTO_NICHE["sources"]:
        lines.append(f"- {source}")

    lines.extend([
        "",
        "Quy trình A -> Z:",
        "1) Dùng niche bot đã chọn: AI tools + SaaS + hosting/VPS",
        "2) Lấy affiliate link từ AppSumo/Amazon/SaaS partner/hosting referral nếu có",
        "3) Cấu hình bot theo dõi URL giá / coupon / lifetime deal / trial page",
        "4) Khi có deal tốt -> bắn Telegram ngay",
        "5) Gắn affiliate link trong message",
        "6) Tạo kênh Telegram hoặc channel niche riêng",
        "7) Nếu traffic tốt -> mở nhóm VIP hoặc nhận sponsor",
        "",
        "Thông tin bạn chỉ cần cung cấp:",
        "- Telegram channel/group để bắn deal",
        "- Affiliate link template nếu bạn có",
        "- Nếu muốn: thêm vài URL cụ thể cần theo dõi",
        "",
        "Thông tin bot đã tự chọn sẵn:",
        "- niche",
        "- keyword ưu tiên",
        "- hướng monetization",
        "- nguồn deal phù hợp server",
        "- Telegram channel/group để bắn deal",
        "",
        "Tôi có thể làm tiếp cho bạn trong code:",
        "- thêm /mmo start để bot tự dùng niche này luôn",
        "- lưu keyword/URL theo dõi mặc định",
        "- so sánh giá và tự bắn deal về Telegram",
        "- format message có sẵn affiliate link",
        "",
        "Phương án phụ an toàn khác:",
    ])

    for item in MMO_PROJECTS[1:4]:
        lines.append(f"- {item['name']}: {item['category']} | {item['how']}")

    lines.append("")
    lines.append("Kết luận: nếu muốn tôi làm từ A -> Z trong repo này, hướng tốt nhất là DEAL BOT + AFFILIATE, không phải ads/surveys.")
    return "\n".join(lines)


def get_mmo_steps_report() -> str:
    lines = [
        "MMO Telegram steps (thực chiến)",
        "1) Mở manager bot và gọi /start",
        "2) Từ manager gọi lệnh mở bot con OpenClaw (theo flow manager hiện tại)",
        "3) Vào đúng khung chat của bot con OpenClaw",
        "4) Gõ /mmo start",
        "5) Sau đó gõ /mmo để xem niche+keyword auto đã chọn",
        "6) Mỗi ngày kiểm tra /mmo status để theo dõi conversion/payout checklist",
        "",
        "Lệnh MMO dùng trong bot con:",
        "- /mmo          : xem chiến lược bot auto chọn",
        "- /mmo start    : nhận checklist khởi động A->Z",
        "- /mmo steps    : xem lại hướng dẫn thao tác Telegram",
        "- /mmo status   : checklist kiểm tra tiền về",
        "- /mmo withdraw : hướng dẫn rút tiền",
    ]
    return "\n".join(lines)


def get_mmo_start_report() -> str:
    lines = [
        "MMO start checklist",
        "Niche đã chọn tự động: AI tools + SaaS + hosting/VPS deals",
        "Keyword đã nạp tự động: ai tool deal, lifetime deal ai, vps coupon, hosting deal, cloud credits...",
        "",
        "Việc cần làm ngay (5-10 phút):",
        "1) Xác nhận Telegram chat/channel nhận alert",
        "2) Ghim message mô tả kênh deal để giữ user",
        "3) Chuẩn bị affiliate link (nếu có) hoặc chạy non-affiliate trước",
        "4) Lưu danh sách 10-20 URL pricing/coupon/lifetime deal",
        "5) Theo dõi click/conversion mỗi ngày",
        "",
        "Mục tiêu tuần đầu:",
        "- Có deal alert đều đặn",
        "- Có click ổn định",
        "- Có conversion đầu tiên",
    ]
    return "\n".join(lines)


def get_mmo_status_report() -> str:
    lines = [
        "MMO status checklist (kiểm tra tiền)",
        "Mở dashboard affiliate và ghi nhận mỗi ngày:",
        "- Clicks",
        "- Conversions",
        "- Pending commission",
        "- Approved commission",
        "- Paid",
        "",
        "Điều kiện có tiền về:",
        "- Có conversion hợp lệ",
        "- Hết thời gian hold/duyệt đơn",
        "- Đạt ngưỡng payout tối thiểu",
        "",
        "Nếu chưa có tiền sau vài ngày:",
        "- Tăng số URL theo dõi",
        "- Tăng chất lượng deal alert",
        "- Tăng tần suất post Telegram",
    ]
    return "\n".join(lines)


def get_mmo_withdraw_report() -> str:
    lines = [
        "MMO withdraw guide",
        "1) Vào mục Payout/Billing của affiliate network",
        "2) Kết nối phương thức nhận tiền (bank/PayPal/Payoneer/crypto)",
        "3) Kiểm tra số dư Approved (không phải Pending)",
        "4) Kiểm tra ngưỡng rút tối thiểu",
        "5) Bấm Withdraw hoặc chờ auto payout theo kỳ",
        "",
        "Lưu ý:",
        "- Bot không giữ tiền",
        "- Tiền nằm ở tài khoản affiliate network của bạn",
    ]
    return "\n".join(lines)


def handle_mmo_command(raw_text: str) -> str:
    text = raw_text.strip().lower()
    if text in {"/mmo", "/mmo info"}:
        return get_mmo_report()
    if text == "/mmo steps":
        return get_mmo_steps_report()
    if text == "/mmo start":
        return get_mmo_start_report()
    if text == "/mmo status":
        return get_mmo_status_report()
    if text == "/mmo withdraw":
        return get_mmo_withdraw_report()

    return (
        "MMO command không hợp lệ. Dùng:\n"
        "/mmo\n"
        "/mmo auto\n"
        "/mmo stop\n"
        "/mmo start\n"
        "/mmo steps\n"
        "/mmo status\n"
        "/mmo withdraw"
    )


def get_mmo_auto_keywords() -> list[str]:
    return list(AUTO_NICHE["keywords"])


def format_mmo_auto_alert(scan_output: dict[str, Any], max_items: int = 3) -> str:
    opportunities = scan_output.get("opportunities", []) if isinstance(scan_output, dict) else []
    if not opportunities:
        return "MMO auto: chưa có deal chênh lệch đủ tốt ở vòng quét này."

    lines = [
        "MMO auto alert: phát hiện deal tiềm năng",
    ]
    for idx, item in enumerate(opportunities[:max_items], start=1):
        title = str(item.get("title") or "Unknown")
        price = float(item.get("price") or 0.0)
        baseline = float(item.get("baseline_price") or 0.0)
        gap_pct = float(item.get("gap_pct") or 0.0)
        keyword = str(item.get("keyword") or "")
        lines.append(
            f"{idx}) {title} | ${price:.2f} vs ${baseline:.2f} | gap {gap_pct:.1f}% | kw={keyword}"
        )
    return "\n".join(lines)


def get_mmo_auto_scan_interval_sec() -> int:
    raw = os.getenv("MMO_SCAN_INTERVAL_SEC", "600").strip()
    try:
        return max(60, min(int(raw), 86400))
    except ValueError:
        return 600


def get_mmo_min_gap_pct() -> float:
    raw = os.getenv("MMO_MIN_GAP_PCT", "12").strip()
    try:
        return max(1.0, min(float(raw), 90.0))
    except ValueError:
        return 12.0


def fetch_affiliate_payout_status() -> dict[str, Any] | None:
    """Optional payout status fetch.

    Configure in .env:
    - MMO_AFFILIATE_STATUS_URL: endpoint returning JSON
    - MMO_AFFILIATE_STATUS_TOKEN: optional bearer token

    Expected JSON fields (at least one):
    - approved_balance
    - pending_balance
    - currency
    - min_withdraw
    """
    url = os.getenv("MMO_AFFILIATE_STATUS_URL", "").strip()
    if not url:
        return None

    token = os.getenv("MMO_AFFILIATE_STATUS_TOKEN", "").strip()
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return None
        return {
            "approved_balance": float(data.get("approved_balance") or 0.0),
            "pending_balance": float(data.get("pending_balance") or 0.0),
            "currency": str(data.get("currency") or "USD"),
            "min_withdraw": float(data.get("min_withdraw") or 0.0),
        }
    except Exception:
        return None
