import json
import asyncio
from datetime import datetime, timedelta
from typing import Generator
from backend.src.registry import GlucoseReading

class SimulationReader:
    """
    Replays historical JSON/CSV data to simulate a live sensor stream.
    Essential for offline development and safety testing.
    """
    def __init__(self, file_path: str, real_time: bool = False):
        self.file_path = file_path
        self.real_time = real_time
        
    def stream(self) -> Generator[GlucoseReading, None, None]:
        """Generator that yields readings from a file."""
        with open(self.file_path, 'r') as f:
            data = json.load(f)
            
        # Expecting a list of entries similar to Nightscout JSON
        for entry in data:
            yield GlucoseReading(
                timestamp=datetime.fromisoformat(entry['dateString'].replace('Z', '+00:00')),
                value=float(entry['sgv']),
                trend=entry.get('direction', 'Flat'),
                source="simulation"
            )
            
    async def run_live_sim(self, interval_sec: int = 5):
        """Simulates a live feed by waiting between readings."""
        for reading in self.stream():
            print(f"SIM: [{reading.timestamp}] {reading.value} mg/dL")
            await asyncio.sleep(interval_sec)

if __name__ == "__main__":
    # Test with dummy data if file exists
    import sys
    if len(sys.argv) > 1:
        reader = SimulationReader(sys.argv[1])
        asyncio.run(reader.run_live_sim(1))
    else:
        print("Usage: python sim_reader.py <path_to_json>")
