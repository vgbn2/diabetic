import logging
from datetime import datetime
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
from diabetic.config import config
from diabetic.registry import GlucoseReading

class AuditLogger:
    """
    Persistent Audit Logger using MongoDB.
    Tracks all alerts, system status changes, and user feedback.
    """
    def __init__(self):
        self.uri = config.MONGO_URI
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.collection = None
        self.logger = logging.getLogger("Bio-Quant.Audit")

        if self.uri:
            try:
                self.client = AsyncIOMotorClient(self.uri)
                self.db = self.client.bio_quant
                self.collection = self.db.audit_logs
                self.logger.info("Connected to MongoDB for audit logging.")
            except Exception as e:
                self.logger.error(f"Failed to connect to MongoDB: {e}")

    async def log_event(self, event_type: str, data: dict, level: str = "INFO"):
        """Stores an event in the database and local logger."""
        timestamp = datetime.now()
        log_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "level": level,
            "data": data
        }

        # Local logging
        log_msg = f"[{event_type}] {data}"
        if level == "ERROR":
            self.logger.error(log_msg)
        elif level == "WARNING":
            self.logger.warning(log_msg)
        else:
            self.logger.info(log_msg)

        # Database persistence
        if self.collection is not None:
            try:
                await self.collection.insert_one(log_entry)
            except Exception as e:
                self.logger.error(f"Failed to persist log to MongoDB: {e}")

    async def log_reading(self, reading: GlucoseReading):
        """Persists a raw glucose reading for long-term audit (Task 7.1.7)."""
        await self.log_event("RAW_READING", reading.model_dump())

    async def log_feedback(self, alert_type: str, action: str):
        """Logs user feedback on alerts (Task 7.1.4)."""
        await self.log_event("USER_FEEDBACK", {
            "alert_type": alert_type,
            "action": action,
            "is_false_alarm": action != "confirm"
        })

if __name__ == "__main__":
    # Test standalone
    import asyncio
    async def test():
        logger = AuditLogger()
        await logger.log_event("TEST_BOOT", {"version": "2.0", "status": "success"})
    
    # asyncio.run(test())
