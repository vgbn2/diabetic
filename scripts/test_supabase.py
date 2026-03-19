from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()
db = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

# Insert a test row
db.table('alerts').insert({
    'timestamp': '2026-03-17T00:00:00+00:00',
    'status': 'TEST',
    'message': 'Supabase connection working',
    'delivered': True
}).execute()

print("Connected successfully")