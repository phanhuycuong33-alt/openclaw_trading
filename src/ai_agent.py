# -*- coding: utf-8 -*-
"""ai_agent.py - AI Agent brain that understands natural language and decides actions.

Uses Groq LLM to:
1. Understand user intent from free-form Vietnamese/English text
2. Classify into action types: BUILD, RUN, DEBUG, SEARCH, CHAT, STATUS
3. Extract parameters (description, url, query, etc.)
4. Generate conversational responses

This is the core that makes the bot behave like ChatGPT.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


_AGENT_SYSTEM_PROMPT = """\
Ban la mot AI developer assistant (giong ChatGPT). 
Nhiem vu: Hieu y dinh nguoi dung va phan loai thanh action.

ACTIONS co the:
- BUILD: Nguoi dung muon tao code/project/script/website/app. Bao gom: "lam", "tao", "viet", "build", "create", "make", "code"
- RUN: Nguoi dung muon chay code da tao. Bao gom: "chay", "run", "execute", "thu", "test"
- DEBUG: Nguoi dung bao loi hoac muon fix. Bao gom: "loi", "error", "fix", "bug", "khong chay", "ko dc", "khong dc", "sai", "debug", "sua"
- SEARCH: Nguoi dung muon tim kiem thong tin tren web. Bao gom: "search", "tim", "google", "tra cuu"
- CHAT: Nguoi dung hoi chuyen binh thuong, hoi kien thuc, hoi y kien
- STATUS: Nguoi dung hoi trang thai he thong
- CONFIRM: Nguoi dung xac nhan (ok, yes, duoc, chay di, start)
- CANCEL: Nguoi dung huy (cancel, stop, dung, thoi)

Tra loi DUNG format JSON (KHONG markdown, KHONG giai thich):
{
  "action": "BUILD|RUN|DEBUG|SEARCH|CHAT|STATUS|CONFIRM|CANCEL",
  "description": "mo ta chi tiet nhiem vu (dung cho BUILD)",
  "query": "tu khoa tim kiem (dung cho SEARCH)",
  "reply": "cau tra loi tu nhien gui cho user",
  "confidence": 0.0-1.0
}

Vi du:
User: "tao 1 website ban hang"
-> {"action": "BUILD", "description": "tao 1 website ban hang", "query": "", "reply": "OK, toi se tao website ban hang cho ban. Cho chut nhe...", "confidence": 0.95}

User: "search google ve bitcoin"
-> {"action": "SEARCH", "description": "", "query": "bitcoin", "reply": "De toi tim kiem ve bitcoin cho ban...", "confidence": 0.9}

User: "chay thu di"
-> {"action": "RUN", "description": "", "query": "", "reply": "OK, toi chay code cho ban nhe!", "confidence": 0.9}

User: "bi loi roi, fix ho toi"
-> {"action": "DEBUG", "description": "", "query": "", "reply": "De toi xem loi gi va sua cho ban...", "confidence": 0.9}

User: "ok"
-> {"action": "CONFIRM", "description": "", "query": "", "reply": "OK!", "confidence": 0.95}
"""


def classify_intent(user_text: str) -> dict[str, Any]:
    """Use Groq LLM to understand what the user wants.
    
    Returns dict with keys: action, description, query, reply, confidence.
    Falls back to rule-based classification if LLM fails.
    """
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    
    if groq_key:
        result = _classify_with_groq(user_text, groq_key)
        if result:
            return result
    
    # Fallback: rule-based classification
    return _classify_rule_based(user_text)


def chat_response(user_text: str, context: str = "") -> str:
    """Generate a conversational response using Groq LLM."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    
    if groq_key:
        result = _chat_with_groq(user_text, context, groq_key)
        if result:
            return result
    
    return "Toi hieu roi. Ban muon toi lam gi tiep?"


def web_search(query: str) -> str:
    """Search the web and return results summary.
    Uses DuckDuckGo instant answer API (free, no key needed).
    """
    try:
        # DuckDuckGo instant answer API
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=10,
        )
        data = resp.json()
        
        results = []
        
        # Abstract/summary
        abstract = data.get("Abstract", "")
        if abstract:
            results.append(f">> {abstract}")
            source = data.get("AbstractSource", "")
            url = data.get("AbstractURL", "")
            if source:
                results.append(f"   Nguon: {source} - {url}")
        
        # Related topics
        topics = data.get("RelatedTopics", [])
        for i, topic in enumerate(topics[:5]):
            text = topic.get("Text", "")
            url = topic.get("FirstURL", "")
            if text:
                results.append(f"{i+1}. {text[:150]}")
                if url:
                    results.append(f"   Link: {url}")
        
        if results:
            return "\n".join(results)
        
        # Fallback: try HTML search scraping
        return _search_fallback(query)
        
    except Exception as e:
        return f"Loi khi search: {e}"


def _search_fallback(query: str) -> str:
    """Fallback search using Google's simple endpoint."""
    try:
        resp = requests.get(
            "https://www.google.com/search",
            params={"q": query, "num": 5},
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
            timeout=10,
        )
        # Simple extraction of text snippets
        import re as _re
        snippets = _re.findall(r'<div[^>]*class="BNeawe[^"]*"[^>]*>(.*?)</div>', resp.text)
        clean = [_re.sub(r'<[^>]+>', '', s).strip() for s in snippets[:6] if len(s) > 20]
        if clean:
            return "\n".join(f"{i+1}. {t[:200]}" for i, t in enumerate(clean))
        return f"Khong tim thay ket qua cho: {query}"
    except Exception:
        return f"Khong the search. Thu lai sau."


def _classify_with_groq(user_text: str, groq_key: str) -> dict[str, Any] | None:
    """Classify user intent using Groq LLM."""
    try:
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": _AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.1,
            "max_tokens": 300,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        
        # Parse JSON from response
        # Try to extract JSON if wrapped in markdown
        json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            # Validate required fields
            if "action" in data:
                data.setdefault("description", "")
                data.setdefault("query", "")
                data.setdefault("reply", "")
                data.setdefault("confidence", 0.5)
                return data
        return None
    except Exception:
        return None


def _chat_with_groq(user_text: str, context: str, groq_key: str) -> str | None:
    """Generate conversational response using Groq."""
    try:
        system = (
            "Ban la mot AI assistant than thien, giong ChatGPT. "
            "Tra loi ngan gon, tu nhien, bang tieng Viet khong dau. "
            "Neu user hoi ve code/tech, tra loi chinh xac. "
            "Neu user hoi chuyen binh thuong, tra loi vui ve."
        )
        if context:
            system += f"\n\nContext hien tai:\n{context}"
        
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.7,
            "max_tokens": 500,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def _classify_rule_based(user_text: str) -> dict[str, Any]:
    """Rule-based fallback when LLM is unavailable."""
    lower = user_text.lower().strip()
    
    # CONFIRM
    if lower in {"ok", "yes", "yep", "duoc", "dc", "chay", "start", "ok duoc", "chay di", "di"}:
        return {"action": "CONFIRM", "description": "", "query": "", "reply": "OK!", "confidence": 0.9}
    
    # CANCEL
    if lower in {"cancel", "stop", "dung", "thoi", "huy"}:
        return {"action": "CANCEL", "description": "", "query": "", "reply": "Da huy.", "confidence": 0.9}
    
    # DEBUG
    debug_kw = ["loi", "error", "fix", "bug", "khong chay", "ko dc", "khong dc", "sai", "debug", "sua", "ko chay", "fail", "ko vao dc", "khong vao dc"]
    if any(k in lower for k in debug_kw):
        return {"action": "DEBUG", "description": "", "query": "", "reply": "De toi xem va sua loi cho ban...", "confidence": 0.8}
    
    # SEARCH
    search_kw = ["search", "tim", "google", "tra cuu", "tim kiem", "len web", "len google"]
    if any(k in lower for k in search_kw):
        # Extract query
        query = lower
        for kw in search_kw:
            query = query.replace(kw, "").strip()
        return {"action": "SEARCH", "description": "", "query": query or user_text, "reply": f"De toi search cho ban...", "confidence": 0.8}
    
    # RUN
    run_kw = ["chay", "run", "execute", "thu", "test thu", "chay thu"]
    if any(k in lower for k in run_kw):
        return {"action": "RUN", "description": "", "query": "", "reply": "OK, toi chay code cho ban!", "confidence": 0.8}
    
    # BUILD
    build_kw = ["lam", "tao", "viet", "build", "create", "make", "code", "project", "script", "website", "web", "app"]
    if any(k in lower for k in build_kw):
        return {"action": "BUILD", "description": user_text, "query": "", "reply": "OK, de toi tao cho ban...", "confidence": 0.8}
    
    # STATUS
    if any(k in lower for k in ["status", "trang thai", "dang chay gi"]):
        return {"action": "STATUS", "description": "", "query": "", "reply": "", "confidence": 0.8}
    
    # Default: CHAT
    return {"action": "CHAT", "description": "", "query": "", "reply": "", "confidence": 0.5}
