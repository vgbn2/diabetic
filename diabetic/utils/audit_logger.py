import asyncio
import sqlite3
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from diabetic.config import config
from diabetic.registry import GlucoseReading
from diabetic.utils.db import db_manager
try:
    from diabetic.ml_engine.metabolic_palace import MetabolicPalace
    PALACE_ENABLED = True
except (ImportError, ModuleNotFoundError):
    PALACE_ENABLED = False

# =============================================================================
# 📖 [AUDIT CONNECTIVITY]
# =Focus: Persistent Logging Initialization (MongoDB + SQLite WAL)
# =============================================================================
class AuditLogger:
    """
    Persistent Audit Logger using MongoDB and local SQLite.
    Tracks all alerts, system status changes, and user feedback.
    """
    def __init__(self):
        self.db_manager = db_manager
        self.local_db_path = config.LOCAL_DB_PATH
        self.logger = logging.getLogger("Bio-Quant.Audit")
        
        # Initialize Collections from Singleton
        self.collection = self.db_manager.audit_logs
        if self.collection is not None:
             self.logger.info("MongoDB Audit Logging enabled via shared singleton.")
        else:
             self.logger.warning("MongoDB URI missing; audit logging restricted to local SQLite.")
        
        self.palace = None
        if PALACE_ENABLED:
            try:
                self.palace = MetabolicPalace()
            except Exception as e:
                self.logger.warning(f"Failed to initialize Metabolic Palace: {e}")
                self.palace = None
        
        # GC Protection for background tasks (Phase 0.5 Remediation)
        self.background_tasks = set()

        # Initialize SQLite (Task 8.1.2)
        try:
            self.local_conn = sqlite3.connect(
                self.local_db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self.sql_lock = asyncio.Lock()
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

# =============================================================================
# 📝 [EVENT LOGGING ENGINE]
# =Focus: JSON Persistence, Semantic Indexing, and Priority Routing
# =============================================================================
    async def log_event(self, event_type: str, data: dict, level: str = "INFO"):
        """Stores an event in the database and local logger."""
        timestamp = datetime.now(timezone.utc)

        def _json_serializable(obj):
            """Helper to sanitize nested dicts for BSON/JSON."""
            if isinstance(obj, dict):
                return {k: _json_serializable(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_json_serializable(i) for i in obj]
            if hasattr(obj, "value"): # Enum fallback
                return obj.value
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "model_dump"):
                return obj.model_dump(mode='json')
            return obj

        sanitized_data = _json_serializable(data)
        
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "level": str(level.value if hasattr(level, "value") else level),
            "data": sanitized_data
        }

        log_msg = f"[{event_type}] {sanitized_data}"
        if level == "ERROR":
            self.logger.error(log_msg)
        elif level == "WARNING":
            self.logger.warning(log_msg)
        else:
            self.logger.info(log_msg)

        if self.collection is not None:
            try:
                # MongoDB handles datetime objects directly, but nested enums fail
                await self.collection.insert_one(log_entry)
            except Exception as e:
                self.logger.error(f"Failed to persist log to MongoDB: {e}")

        if hasattr(self, 'local_conn'):
            try:
                def _write_db():
                    cursor = self.local_conn.cursor()
                    cursor.execute(
                        "INSERT INTO audit_logs (timestamp, event_type, level, data) VALUES (?, ?, ?, ?)",
                        (timestamp.isoformat(), event_type, str(level), json.dumps(sanitized_data))
                    )
                    self.local_conn.commit()

                async with self.sql_lock:
                    await asyncio.to_thread(_write_db)
            except Exception as e:
                self.logger.error(f"Failed to persist log to SQLite: {e}")

        # Semantic Indexing (Layer 4/5 Trigger)
        if self.palace and (level in ["WARNING", "ERROR"] or event_type in ["USER_FEEDBACK", "REGIME_SHIFT"]):
            try:
                # Palace expect flat/simple dicts
                task = asyncio.create_task(asyncio.to_thread(
                    self.palace.remember_snapshot, {
                        "event_type": event_type,
                        "timestamp": timestamp.isoformat(),
                        "level": str(level),
                        **sanitized_data
                    }, 
                    room="l4_anomaly_audit" if level != "INFO" else "l5_user_feedback"
                ))
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)
            except Exception as e:
                self.logger.error(f"Failed to semantically index event: {e}")

# =============================================================================
# 🩸 [TELEMETRY & USER FEEDBACK]
# =Focus: Raw Reading Persistence and RLHF Feedback Loops
# =============================================================================
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

    async def get_recent_feedback(self, alert_type: str, hours: int = 24) -> List[dict]:
        """Retrieves recent RLHF feedback for fine-tuning sensitivity."""
        if not hasattr(self, 'local_conn'):
            return []

        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            def _query_db():
                cursor = self.local_conn.cursor()
                cursor.execute(
                    "SELECT data FROM audit_logs WHERE event_type = ? AND timestamp > ?",
                    ("USER_FEEDBACK", cutoff.isoformat())
                )
                return cursor.fetchall()
            
            rows = await asyncio.to_thread(_query_db)
            feedback = []
            for row in rows:
                data = json.loads(row[0])
                if data.get("alert_type") == alert_type:
                    feedback.append(data)
            return feedback
        except Exception as e:
            self.logger.error(f"Failed to query recent feedback: {e}")
            return []


# =============================================================================
# 🛡️ [ADMINISTRATIVE INTEGRITY]
# =Focus: Secure Tracking of Maintenance and System Overrides
# =============================================================================
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