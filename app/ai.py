import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.config import Settings

logger = logging.getLogger(__name__)


def build_system_message(settings: Settings, email_count: int) -> str:
    tz = settings.user_timezone
    try:
        today_local = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    except Exception:
        today_local = datetime.now().strftime("%Y-%m-%d")

    return f"""You are a business email assistant. You help staff analyze incoming emails.

STRICT RULES:
1. Use ONLY the emails provided below. Do NOT use outside knowledge.
2. If the answer is not contained in the provided emails, respond exactly:
   "Not available in current emails."
3. Do NOT assume, infer, or fabricate any information not explicitly stated.
4. Always cite the email number (e.g. "Email #3") when referring to a specific message. Email numbers MUST match the numbering in the provided list (Email #1 is the first block, etc.).
5. Use bullet points. Mention branch and account names when relevant.
6. Be concise. No filler text.
7. Do NOT repeat full email content unless the user explicitly asks for the full text of a specific email.
8. Do NOT expose sensitive or personal information (names, addresses, contact details) unless explicitly asked.
9. Default to 1–3 bullet points unless the user explicitly asks for more detail or the full text.
10. Group similar emails together when helpful (same sender or same topic).
11. When counting emails, give exact numbers (e.g. "2 emails from X").
12. Answer ONLY what the user asked. Do not add unrelated explanation or topics.
13. If the user asks what someone said, quoted, or the exact content of a specific email, include the key relevant lines or phrases (still concise, not the entire thread unless asked).

Current batch: {email_count} emails loaded (up to last {settings.max_emails}).
Today (local): {today_local}  |  Timezone: {tz}
"""


def build_user_message(context: str, query: str) -> str:
    return f"""Emails:
{context}

Question: {query}
"""


def estimate_overhead_tokens(settings: Settings, query: str) -> int:
    from app.tokens import count_tokens

    sys_t = build_system_message(settings, email_count=0)
    wrap = f"""Emails:


Question: {query}"""
    return count_tokens(sys_t, settings.gemini_model) + count_tokens(
        wrap, settings.gemini_model
    )


async def ask_ai(
    settings: Settings,
    *,
    context: str,
    query: str,
    email_count: int,
) -> str:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=settings.gemini_api_key)
    system = build_system_message(settings, email_count=email_count)
    user = build_user_message(context, query)
    
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=settings.gemini_max_tokens,
    )

    last_exc: Exception | None = None
    try:
        for attempt in range(3):
            try:
                resp = await client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=user,
                    config=config,
                )
                return resp.text or ""
            except APIError as e:
                # 429 is resource exhausted for Gemini
                if getattr(e, "code", None) == 429 or "429" in str(e):
                    last_exc = e
                    wait_s = 0.5 * (2**attempt)
                    logger.warning("gemini_rate_limit attempt=%s wait_s=%s", attempt + 1, wait_s)
                    await asyncio.sleep(wait_s)
                else:
                    raise e
    except Exception as e:
        last_exc = e

    if last_exc:
        raise last_exc
    return ""
