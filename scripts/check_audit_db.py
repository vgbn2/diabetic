import sqlite3
import json

db_path = r"C:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor\storage\audit.db"
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 10;")
    rows = cursor.fetchall()
    for row in rows:
        print(row)
    conn.close()
except Exception as e:
    print(f"Error: {e}")
