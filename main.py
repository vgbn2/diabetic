import asyncio
import sys
import os

# Add current directory to sys.path to allow 'from diabetic...' imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from diabetic.main import main as diabetic_main

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(diabetic_main())
    except KeyboardInterrupt:
        print("\nSystem shutdown complete.")
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        loop.close()
