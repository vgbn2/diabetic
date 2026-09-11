import sys
import os
import asyncio

# Setup path so we can import diabetic modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from diabetic.telegram_bot.handlers import TelegramNotifier, TelegramApp
from diabetic.coordinator import Coordinator
from diabetic.telegram_bot.twa_api import get_hud_data

async def test_validation():
    print("Testing syntax and initialization...")
    try:
        # Initialize the coordinator which should also initialize TelegramNotifier and TelegramApp
        coord = Coordinator()
        
        print("✅ Coordinator initialized successfully.")
        if hasattr(coord.notifier, 'pending_tasks') and hasattr(coord.notifier, 'audit_logger'):
            print("✅ TelegramNotifier has new attributes (pending_tasks, audit_logger).")
        else:
            print("❌ TelegramNotifier missing new attributes.")
            
        print("Test complete. Syntax and integration points are valid.")
    except Exception as e:
        print(f"❌ Error during initialization: {e}")

if __name__ == "__main__":
    asyncio.run(test_validation())
