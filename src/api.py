from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
import time
from .data_models import BiometricReading

app = Flask(__name__)
CORS(app)

# These will be set by coordinator on startup
shared_engine = None

@app.route('/api/ingest/pulse', methods=['POST'])
def ingest_pulse():
    """Endpoint for external apps/devices to POST pulse (BPM) and HRV (ms)."""
    if not shared_engine:
        return jsonify({'error': 'Engine not initialized'}), 500
    
    data = request.json
    hr = data.get('hr')
    rmssd = data.get('rmssd')
    
    if hr is None and rmssd is None:
        return jsonify({'error': 'Missing pulse (hr) or HRV (rmssd) data'}), 400
    
    # Create biometric event and inject into the engine's event bus
    reading = BiometricReading(
        timestamp=datetime.now(),
        hr=hr,
        rmssd=rmssd,
        source=data.get('source', 'External_API')
    )
    
    # Note: We must use the running loop to put into the async queue
    # Since start_api runs in a thread, we use call_soon_threadsafe or similar
    # But since engine is shared, we'll try to put it directly if the queue is not thread-bound (it is)
    # A simpler way is to just append to the engine's buffer directly since it's a list
    shared_engine.hrv_buffer.append(reading)
    if len(shared_engine.hrv_buffer) > 100: shared_engine.hrv_buffer.pop(0)
    
    return jsonify({'status': 'Pulse received', 'hr': hr, 'rmssd': rmssd})

@app.route('/api/state')
def get_state():
    if not shared_engine:
        return jsonify({'error': 'Engine not initialized'})

    hrv_data = []
    hr_data = []
    glucose_data = []

    # Use shallow copies to prevent RuntimeError: list changed size during iteration
    hrv_copy = list(shared_engine.hrv_buffer)
    cgm_copy = list(shared_engine.cgm_buffer)

    for r in hrv_copy[-50:]:
        if r.rmssd:
            hrv_data.append({
                'time': int(r.timestamp.timestamp()),
                'value': r.rmssd
            })
        if r.hr:
            hr_data.append({
                'time': int(r.timestamp.timestamp()),
                'value': r.hr
            })

    for r in cgm_copy[-50:]:
        glucose_data.append({
            'time': int(r.timestamp.timestamp()),
            'value': r.sgv
        })

    return jsonify({
        'hrv': hrv_data,
        'pulse': hr_data,
        'glucose': glucose_data,
        'dsi': shared_engine.stress_tracker.get_current_dsi(),
        'status': getattr(shared_engine, 'last_status', 'STABLE')
    })

def start_api():
    app.run(port=5000, debug=False, use_reloader=False)
