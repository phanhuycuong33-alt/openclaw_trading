from __future__ import annotations

from typing import Any


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


def get_mmo_report() -> str:
    lines = [
        "MMO / self-hosted ideas (GitHub-based)",
        "Lưu ý: không có repo nào 'chỉ chạy server là tự ra tiền'. Cần traffic, data hoặc khách hàng.",
        "Top an toàn/thực tế: changedetection.io, n8n, Ghost.",
        "",
    ]

    for idx, item in enumerate(MMO_PROJECTS[:6], start=1):
        top_mark = " [TOP]" if item["name"] in TOP_SAFE else ""
        lines.append(f"{idx}) {item['name']}{top_mark}")
        lines.append(f"   Repo: {item['repo']}")
        lines.append(f"   Nhóm: {item['category']}")
        lines.append(f"   Kiếm tiền: {item['how']}")
        lines.append(f"   Budget: {item['budget']} | Độ khó: {item['difficulty']} | Risk: {item['risk']}")
        lines.append(f"   Fit: {item['fit']}")
        lines.append("")

    lines.append("Gợi ý nhanh:")
    lines.append("- Muốn dễ triển khai nhất: dùng changedetection.io để săn deal + Telegram + affiliate")
    lines.append("- Muốn bán dịch vụ: dùng n8n hoặc Chatwoot")
    lines.append("- Muốn bền vững: dùng Ghost + SEO + newsletter")
    return "\n".join(lines)
