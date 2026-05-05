import asyncio
import httpx
import time

from app.config import get_settings
from app.email_client import fetch_emails, _extract_message_list

async def run():
    settings = get_settings()
    settings.mock_emails = False
    
    start = time.time()
    # Use setting's timeout which provides a much larger window
    async with httpx.AsyncClient(timeout=settings.email_api_timeout) as client:
        try:
            emails = await fetch_emails(client, settings, for_today=False)
            print("Successfully fetched:", len(emails), "in", time.time() - start, "seconds")
        except Exception as e:
            print("Failed to fetch after", time.time() - start, "seconds:")
            print(type(e), str(e))

if __name__ == "__main__":
    asyncio.run(run())
