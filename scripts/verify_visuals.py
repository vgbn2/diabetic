import asyncio
import os
from datetime import datetime, timezone
from diabetic.utils.audit_logger import AuditLogger
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.ui.visualizer import MetabolicVisualizer

async def verify():
    print("--- Phase 1: Persistence ---")
    audit = AuditLogger()
    reading = GlucoseReading(
        timestamp=datetime.now(timezone.utc),
        value=10.5,
        trend="Flat"
    )
    await audit.log_reading(reading)
    last_ts = await audit.get_last_reading_timestamp()
    print(f"Last recorded timestamp: {last_ts}")
    
    print("\n--- Phase 2: Visualization ---")
    viz = MetabolicVisualizer(output_dir="test_charts")
    
    from diabetic.registry import CardiacReading
    cardiac = CardiacReading(timestamp=datetime.now(timezone.utc), bpm=72, hrv=50.0)
    snapshot = MetabolicSnapshot(glucose=reading, cardiac=cardiac)
    snapshot.velocity = 0.5
    
    # Simulate a few snapshots
    snapshots = [snapshot]
    viz.update_continuous(snapshots)
    
    if os.path.exists("test_charts/live_dashboard.png"):
        print("Success: live_dashboard.png generated.")
    else:
        print("Error: live_dashboard.png NOT found.")

if __name__ == "__main__":
    asyncio.run(verify())
