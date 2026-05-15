import asyncio
from app.config import get_settings
from app.domain.ai_service import summarize_emails

async def main():
    settings = get_settings()
    
    print("Asking OpenClaw Agent to summarize recent emails...")
    
    try:
        response = await summarize_emails(
            settings=settings,
            context="", 
            query="Please summarize my most recent important emails.",
            email_count=0
        )
        print("\n--- OPENCLAW RESPONSE ---")
        print(response)
    except Exception as e:
        print(f"\nFailed! Make sure OpenClaw is running on port 18789. Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
