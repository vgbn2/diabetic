import asyncio
import logging
import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from diabetic.ingestion.cardiac import HeartRateIngestor
from diabetic.config import config

async def verify_cardiac():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    logger = logging.getLogger("Bio-Quant.Verify.Cardiac")
    
    print("\n" + "="*50)
    print("BIOMETRIC AUDIT: HEART RATE AGGREGATE VERIFICATION")
    print("="*50 + "\n")
    
    ingestor = HeartRateIngestor()
    
    # 1. Simulate 30 seconds of mock data accumulation
    logger.info("Step 1: Simulating 30 seconds of resting biometric data...")
    for _ in range(30):
        # In mock mode, fetch_latest() calls _generate_mock_reading() internally
        # which appends to bpm_aggregate.
        await ingestor.fetch_latest(reset=False)
    
    # Check intermediate state
    print(f"DEBUG: Accumulator Count: {len(ingestor.bpm_aggregate)} readings")
    
    # 2. Inject a Tachycardia Stress Event (Manual override of aggregate)
    logger.info("Step 2: Injecting a simulated Tachycardia Stress Spike (145 BPM)...")
    ingestor.bpm_aggregate.append(142)
    ingestor.bpm_aggregate.append(145) # Peak
    ingestor.bpm_aggregate.append(141)
    
    # 3. Final Fetch (The 5-min Summary)
    logger.info("Step 3: Executing Metabolic Summary Fetch...")
    summary = await ingestor.fetch_latest(reset=True)
    
    if summary:
        print("\n" + "-"*30)
        print("METABOLIC SNAPSHOT SUMMARY")
        print(f"Timestamp:      {summary.timestamp}")
        print(f"Instant BPM:    {summary.bpm} (at t=0)")
        print(f"Mean BPM:       {summary.mean_bpm} (Resting average)")
        print(f"Peak BPM:       {summary.max_bpm} <--- [STRESS SPIKE CAPTURED]")
        print(f"HRV (RMSSD):    {summary.hrv}")
        print(f"Signal Quality: {summary.signal_quality:.2%}")
        print("-"*30 + "\n")
        
        # 4. Verify Reset
        print(f"Post-Fetch Buffer Count: {len(ingestor.bpm_aggregate)} (Should be 0)")
        
        if len(ingestor.bpm_aggregate) == 0 and summary.max_bpm >= 145:
            print("\nRESULT: [SUCCESS] HEART RATE AGGREGATOR HARDENED.")
        else:
            print("\nRESULT: [FAIL] SPIKE NOT CAPTURED OR RESET FAILED.")
    else:
        print("\nRESULT: [FAIL] NO DATA RETURNED.")

if __name__ == "__main__":
    asyncio.run(verify_cardiac())
