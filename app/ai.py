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
4. Do NOT include or cite the internal email numbers (e.g. "Email #1", "Email #2") in your response. Refer to the emails by their sender or subject instead.
5. Mention branch and account names ONLY if explicitly present in the email.
6. Be concise. No filler text.
7. Do NOT repeat full email content unless the user explicitly asks for the full text of a specific email.
8. Sender names and email subjects are NOT sensitive — always include them in responses. Only avoid exposing phone numbers, physical addresses, or private personal data unless explicitly asked.
9. DO NOT group emails together unless explicitly asked. Always list the exact number of emails requested as separate bullet points.
10. When counting emails, give exact numbers (e.g. "2 emails from X").
11. Answer ONLY what the user asked. Do not add unrelated explanation or topics.
12. Do not add advice unless it is explicitly mentioned in the email.
13. If the user asks about a single email, respond in a natural paragraph (no bullet points, no labels like From/Subject).
14. If the user asks about multiple emails, respond with short bullet points (one line per email).
15. Do NOT include "From:", "Subject:", or "Summary:" labels in the output.
16. Write summaries in a human-friendly, natural tone (like how a person would speak). Avoid robotic phrases like "Here are..." or "The following..."
17. Ensure responses are complete and not cut off.
18. For sender-based queries (e.g., "any mail from LinkedIn"):
    - Do NOT include email addresses or "Subject" lines.
    - Summarize each email in natural language.
    - Do NOT repeat the sender's name in every bullet if it's already implied by the user's question. (e.g., if asked for GitHub emails, say "A security alert providing..." instead of "GitHub email...").
    - Use short bullet points.
19. "Priority" or "Urgent" emails ONLY include security alerts, direct messages from people, or critical account updates. Social media notifications (Instagram, LinkedIn, Facebook), project collaboration invites, newsletters, and marketing are NEVER priority.
20. NEVER include raw email addresses (e.g., noreply@..., notifications@...) in any response unless the user explicitly asks for them.
21. When answering yes/no or priority questions (e.g., "any priority mails?"):
    - Start with a natural human response like: "Yes, you have a few priority emails." OR "No, you don't have any priority emails."
    - Strictly exclude social media, promotions, and non-critical updates from priority.
    - Avoid robotic phrases like "Here are..." or "The following..."
22. Do NOT repeat duplicate emails. Group similar emails together.
23. Do NOT exaggerate counts. If multiple similar emails exist, group them and describe collectively (e.g., "Microsoft emails with verification codes") instead of counting each one.

EXAMPLES:
User: summarize last 3 emails
Assistant:
- GitHub email with a sudo authentication code.
- Postman email about Enterprise trial access levels.
- LinkedIn suggestion to connect with Hitesh Murthy.S.

User: what is my last mail?
Assistant:
Your latest email is about a security login alert, informing you of a new device login and advising you to take action if it wasn't you.

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
                    logger.warning(
                        "gemini_rate_limit attempt=%s wait_s=%s",
                        attempt + 1,
                        wait_s,
                    )
                    await asyncio.sleep(wait_s)
                else:
                    raise e
    except Exception as e:
        last_exc = e

    if last_exc:
        raise last_exc

    return ""