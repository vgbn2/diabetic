import asyncio
import sqlite3
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorClient
from diabetic.config import config
from diabetic.registry import GlucoseReading
try:
    from diabetic.ml_engine.metabolic_palace import MetabolicPalace
    PALACE_ENABLED = True
except (ImportError, ModuleNotFoundError):
    PALACE_ENABLED = False

class AuditLogger:
    """
    Persistent Audit Logger using MongoDB and local SQLite.
    Tracks all alerts, system status changes, and user feedback.
    """
    def __init__(self):
        self.uri = config.MONGO_URI
        self.local_db_path = config.LOCAL_DB_PATH
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.collection = None
        self.logger = logging.getLogger("Bio-Quant.Audit")
        
        self.palace = None
        if PALACE_ENABLED:
            try:
                self.palace = MetabolicPalace()
            except Exception as e:
                self.logger.warning(f"Failed to initialize Metabolic Palace: {e}")
                self.palace = None

        # Initialize MongoDB (connect if URI provided)
        if self.uri:
            try:
                self.client = AsyncIOMotorClient(self.uri, serverSelectionTimeoutMS=5000)
                self.db = self.client["bio_quant"]
                self.collection = self.db["audit_logs"]
                self.logger.info("MongoDB client initialised.")
            except Exception as e:
                self.logger.warning(f"MongoDB connection failed (cloud logging disabled): {e}")

        # Initialize SQLite (Task 8.1.2)
        try:
            self.local_conn = sqlite3.connect(
                self.local_db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self.local_conn.execute("PRAGMA journal_mode=WAL")
            self.local_conn.execute("PRAGMA synchronous=NORMAL")
            self._init_sqlite()
            self.logger.info(f"Local SQLite initialized at {self.local_db_path} (WAL Mode enabled)")
        except Exception as e:
            self.logger.error(f"Failed to initialize local SQLite: {e}")

    def _init_sqlite(self):
        """Creates the necessary tables for local persistence."""
        cursor = self.local_conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                level TEXT NOT NULL,
                data TEXT
            )
        """)
        self.local_conn.commit()

    async def log_event(self, event_type: str, data: dict, level: str = "INFO"):
        """Stores an event in the database and local logger."""
        timestamp = datetime.now(timezone.utc)

        def _default(o):
            if isinstance(o, datetime):
                return o.isoformat()
            if hasattr(o, "model_dump"):
                return o.model_dump(mode='json')
            if hasattr(o, "dict"):
                return o.dict()
            return str(o)

        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "level": level,
            "data": data
        }

        log_msg = f"[{event_type}] {data}"
        if level == "ERROR":
            self.logger.error(log_msg)
        elif level == "WARNING":
            self.logger.warning(log_msg)
        else:
            self.logger.info(log_msg)

        if self.collection is not None:
            try:
                await self.collection.insert_one(log_entry)
            except Exception as e:
                self.logger.error(f"Failed to persist log to MongoDB: {e}")

        if hasattr(self, 'local_conn'):
            try:
                def _write_db():
                    cursor = self.local_conn.cursor()
                    cursor.execute(
                        "INSERT INTO audit_logs (timestamp, event_type, level, data) VALUES (?, ?, ?, ?)",
                        (timestamp.isoformat(), event_type, level, json.dumps(data, default=_default))
                    )
                    self.local_conn.commit()

                await asyncio.to_thread(_write_db)
            except Exception as e:
                self.logger.error(f"Failed to persist log to SQLite: {e}")

        # Semantic Indexing (Layer 4/5 Trigger)
        if self.palace and (level in ["WARNING", "ERROR"] or event_type in ["USER_FEEDBACK", "REGIME_SHIFT"]):
            try:
                task = asyncio.create_task(asyncio.to_thread(
                    self.palace.remember_snapshot, {
                        "event_type": event_type,
                        "timestamp": timestamp.isoformat(),
                        "level": level,
                        **data
                    }, 
                    room="l4_anomaly_audit" if level != "INFO" else "l5_user_feedback"
                ))
            except Exception as e:
                self.logger.error(f"Failed to semantically index event: {e}")

    async def log_reading(self, reading: GlucoseReading):
        """Persists a raw glucose reading for long-term audit (Task 7.1.7)."""
        await self.log_event("RAW_READING", reading.model_dump())

    async def get_last_reading_timestamp(self) -> Optional[datetime]:
        """
        Retrieves the most recent raw reading timestamp from SQLite.
        Used for Stateful Resumption (Wave 2).
        """
        if not hasattr(self, 'local_conn'):
            return None

        try:
            def _query_db():
                cursor = self.local_conn.cursor()
                cursor.execute(
                    "SELECT timestamp FROM audit_logs WHERE event_type = ? ORDER BY timestamp DESC LIMIT 1",
                    ("RAW_READING",)
                )
                return cursor.fetchone()

            row = await asyncio.to_thread(_query_db)
            if row:
                return datetime.fromisoformat(row[0])
        except Exception as e:
            self.logger.error(f"Failed to query local last timestamp: {e}")
        return None

    async def log_feedback(self, alert_type: str, action: str):
        """Logs user feedback on alerts (Task 7.1.4)."""
        await self.log_event("USER_FEEDBACK", {
            "alert_type": alert_type,
            "action": action,
            "is_false_alarm": action != "confirm"
        })

    async def log_admin_action(self, action_name: str, details: dict):
        """Logs sensitive administrative actions (Task III)."""
        await self.log_event("ADMIN_ACTION", {
            "action": action_name,
            **details
        }, level="WARNING")

if __name__ == "__main__":
    import asyncio
    async def test():
        logger = AuditLogger()
        await logger.log_event("TEST_BOOT", {"version": "2.0", "status": "success"})
    # asyncio.run(test())