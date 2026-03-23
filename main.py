import asyncio
import sys
import logging
from backend.src.config import config
from backend.src.coordinator import Coordinator

async def main():
    """
    Main entry point for Bio-Quant Hyperglycemia-Faint Predictor.
    Unified Architecture v2.0
    """
    print("="*60)
    print("  BIO-QUANT: METABOLIC INFERENCE ENGINE (v2.0)  ")
    print("="*60)
    
    # Initialize Coordinator (Orchestrates Filter, Analysis, Alerts, Persistence)
    system = Coordinator()
    
    try:
        # Start the live processing loop
        # This handles Nightscout polling, Kalman filtering, and Telegram notifications
        await system.start_live_mode()
    except Exception as e:
        logging.error(f"System Failure: {e}")
    finally:
        system.stop()

if __name__ == "__main__":
    # Windows Selector Loop for high-concurrency async
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Bio-Quant Shutdown Initiated by User.")
    except Exception as e:
        print(f"\n[CRITICAL] System Unhandled Exception: {e}")
