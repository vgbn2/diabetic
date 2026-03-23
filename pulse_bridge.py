import requests
import time
import random
from datetime import datetime

# Bio-Quant API Configuration
API_URL = "http://127.0.0.1:5000/api/ingest/pulse"

def monitor_and_send_pulse():
    """
    Simulates a pulse monitor (e.g., from a wearable or sensor).
    Replace the 'hr' variable with real data from your device SDK.
    """
    print("🚀 Bio-Quant Pulse Bridge Started...")
    print(f"Sending data to: {API_URL}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            # SIMULATION: Replace this with your actual sensor reading logic
            # Example: hr = my_sensor.get_heart_rate()
            hr = random.randint(65, 85) # Normal resting heart rate
            rmssd = random.randint(40, 60) # Normal HRV
            
            payload = {
                "hr": hr,
                "rmssd": rmssd,
                "source": "Local_Bridge_Script"
            }
            
            try:
                response = requests.post(API_URL, json=payload, timeout=2)
                if response.status_code == 200:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent Pulse: {hr} BPM | HRV: {rmssd} ms")
                else:
                    print(f"❌ Error: {response.json().get('error')}")
            except requests.exceptions.ConnectionError:
                print("⚠️ Bio-Quant Engine not running. Start 'python main.py' first.")
            
            # Send every 10 seconds
            time.sleep(10)
            
    except KeyboardInterrupt:
        print("\nPulse Bridge stopped.")

if __name__ == "__main__":
    monitor_and_send_pulse()
