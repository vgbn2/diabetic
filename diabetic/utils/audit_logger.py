import asyncio
import sqlite3
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List
from urllib.parse import quote

from diabetic.config import config
from diabetic.registry import GlucoseReading
from diabetic.utils.db import db_manager

@dataclass(frozen=True)
class AuditWriteResult:
    local_persisted: bool
    mongo_persisted: bool

    @property
    def durable(self) -> bool:
        return self.local_persisted


# =============================================================================
# 📖 [AUDIT CONNECTIVITY]
# =Focus: Persistent Logging Initialization (MongoDB + SQLite WAL)
# =============================================================================
class LocalAuditReader:
    """Own a read-only local audit connection for one bounded query scope."""

    def __init__(self, local_db_path: str | Path):
        self.local_db_path = Path(local_db_path)
        self.local_conn: Optional[sqlite3.Connection] = None
        self.closed = False

    async def __aenter__(self) -> "LocalAuditReader":
        if self.closed:
            raise RuntimeError("local audit reader is closed")
        if self.local_conn is None and self.local_db_path.is_file():
            uri = f"file:{quote(str(self.local_db_path.resolve()))}?mode=ro"
            self.local_conn = await asyncio.to_thread(
                sqlite3.connect,
                uri,
                uri=True,
                check_same_thread=False,
                timeout=5.0,
            )
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.close()

    async def get_last_reading_timestamp(self) -> Optional[datetime]:
        connection = self.local_conn
        if connection is None:
            return None

        def _query_db():
            cursor = connection.execute(
                "SELECT timestamp FROM audit_logs "
                "WHERE event_type = ? ORDER BY timestamp DESC LIMIT 1",
                ("RAW_READING",),
            )
            return cursor.fetchone()

        try:
            row = await asyncio.to_thread(_query_db)
        except sqlite3.Error:
            return None
        return datetime.fromisoformat(row[0]) if row else None

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        connection, self.local_conn = self.local_conn, None
        if connection is not None:
            await asyncio.to_thread(connection.close)


class AuditLogger:
    """
    Persistent Audit Logger using MongoDB and local SQLite.
    Tracks all alerts, system status changes, and user feedback.
    """
    def __init__(self, local_db_path: Optional[str] = None):
        self.db_manager = db_manager
        self.local_db_path = local_db_path or config.LOCAL_DB_PATH
        self.logger = logging.getLogger("Bio-Quant.Audit")
        
        # Initialize Collections from Singleton
        self.collection = self.db_manager.audit_logs
        if self.collection is not None:
             self.logger.info("MongoDB Audit Logging enabled via shared singleton.")
        else:
             self.logger.warning("MongoDB URI missing; audit logging restricted to local SQLite.")
        
        # GC Protection for background tasks (Phase 0.5 Remediation)
        self.background_tasks = set()
        self.closed = False

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
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS glucose_gaps (
                gap_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                state TEXT NOT NULL,
                reason TEXT,
                from_event_id TEXT,
                through_event_id TEXT,
                from_timestamp TEXT,
                through_timestamp TEXT,
                updated_at TEXT NOT NULL
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

        mongo_persisted = False
        if self.collection is not None:
            try:
                # MongoDB handles datetime objects directly, but nested enums fail
                await self.collection.insert_one(log_entry)
                mongo_persisted = True
            except Exception as e:
                self.logger.error(
                    "Failed to persist log to MongoDB: %s", e.__class__.__name__
                )

        local_persisted = False
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
                local_persisted = True
            except Exception as e:
                self.logger.error(
                    "Failed to persist log to SQLite: %s", e.__class__.__name__
                )
        return AuditWriteResult(
            local_persisted=local_persisted,
            mongo_persisted=mongo_persisted,
        )

    async def record_glucose_gap(self, payload: dict) -> AuditWriteResult:
        """Upsert machine-verifiable glucose reconciliation state before coalescing."""
        result = await self.log_event("GLUCOSE_GAP", payload, level="WARNING")
        local_persisted = False
        if hasattr(self, "local_conn"):
            try:
                now = datetime.now(timezone.utc).isoformat()

                def _write_gap():
                    self.local_conn.execute(
                        """
                        INSERT INTO glucose_gaps (
                            gap_id, source, state, reason, from_event_id,
                            through_event_id, from_timestamp, through_timestamp,
                            updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(gap_id) DO UPDATE SET
                            state = excluded.state,
                            through_event_id = COALESCE(
                                excluded.through_event_id,
                                glucose_gaps.through_event_id
                            ),
                            through_timestamp = COALESCE(
                                excluded.through_timestamp,
                                glucose_gaps.through_timestamp
                            ),
                            updated_at = excluded.updated_at
                        """,
                        (
                            payload["gap_id"],
                            payload["source"],
                            payload["state"],
                            payload.get("reason"),
                            payload.get("from_event_id"),
                            payload.get("through_event_id"),
                            payload.get("from_timestamp"),
                            payload.get("through_timestamp"),
                            now,
                        ),
                    )
                    self.local_conn.commit()

                async with self.sql_lock:
                    await asyncio.to_thread(_write_gap)
                local_persisted = True
            except Exception as error:
                self.logger.error(
                    "Failed to persist glucose gap projection: %s",
                    error.__class__.__name__,
                )
        return AuditWriteResult(
            local_persisted=local_persisted,
            mongo_persisted=result.mongo_persisted,
        )

    async def get_pending_glucose_gaps(self) -> List[dict]:
        if not hasattr(self, "local_conn"):
            return []

        def _query_gaps():
            cursor = self.local_conn.execute(
                """
                SELECT gap_id, source, reason, from_event_id, through_event_id,
                       from_timestamp, through_timestamp
                FROM glucose_gaps
                WHERE state = 'replay_pending'
                ORDER BY updated_at, gap_id
                """
            )
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        try:
            return await asyncio.to_thread(_query_gaps)
        except Exception as error:
            self.logger.error(
                "Failed to query glucose gap projection: %s",
                error.__class__.__name__,
            )
            return []

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

    async def close(self) -> None:
        """Idempotently close the local writer connection owned by this logger."""
        if self.closed:
            return
        self.closed = True
        connection = getattr(self, "local_conn", None)
        if connection is not None:
            del self.local_conn
            await asyncio.to_thread(connection.close)

    async def log_feedback(
        self,
        alert_type: str,
        action: str,
        *,
        alert_id: Optional[str] = None,
    ) -> AuditWriteResult:
        """Log feedback, binding new callbacks to an opaque alert ID."""
        normalized_action = action.strip().lower()
        return await self.log_event("USER_FEEDBACK", {
            "alert_id": alert_id,
            "alert_type": alert_type,
            "action": action,
            "is_false_alarm": normalized_action in {"false", "false_alarm"},
            "is_confirmed": normalized_action in {"confirm", "confirmed"},
            "is_neutral": normalized_action == "neutral"
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
    async def log_admin_action(self, action_name: str, details: dict) -> AuditWriteResult:
        """Log an administrative action and expose local durability."""
        return await self.log_event("ADMIN_ACTION", {
            "action": action_name,
            **details
        }, level="WARNING")

if __name__ == "__main__":
    import asyncio
    async def test():
        logger = AuditLogger()
        await logger.log_event("TEST_BOOT", {"version": "2.0", "status": "success"})
    # asyncio.run(test())
