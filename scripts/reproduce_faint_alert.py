import sys
import os
import asyncio
from datetime import datetime

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(PROJECT_ROOT)

from diabetic.config import config
from diabetic.telegram_bot.handlers import TelegramNotifier
from diabetic.telegram_bot.decision_matrix import Alert, AlertSeverity

async def trigger_live_test():
    """
    Triggers a simulated FAINT_RISK alert to verify Telegram connectivity.
    """
    print("--- Bio-Quant Telegram Alert Trigger ---")
    
    if not config.TELEGRAM_TOKEN or config.USER_ID == 0:
        print("❌ ERROR: TELEGRAM_TOKEN or USER_ID not set in .env")
        print("Please ensure your .env file contains:")
        print("TELEGRAM_TOKEN=your_token_here")
        print("USER_ID=your_chat_id_here")
        return

    notifier = TelegramNotifier()
    
    # Create a simulated high-risk alert
    alert = Alert(
        timestamp=datetime.now(),
        type="FAINT_RISK",
        severity=AlertSeverity.HIGH,
        message="Simulated rapid glucose climb detected (+1.2 mmol/L/5min). Please confirm state.",
        glucose_value=17.5,
        prediction_30m=21.4
    )
    
    print(f"Propagating alert to Chat ID: {config.USER_ID}...")
    await notifier.send_alert(alert)
    print("✅ Alert sent! Check your Telegram.")

if __name__ == "__main__":
    asyncio.run(trigger_live_test())
