from matplotlib.path import Path
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from motor.motor_asyncio import AsyncIOMotorClient
from diabetic.config import config
from diabetic.registry import GlucoseReading, InsulinDose, MealEvent

# =============================================================================
# 🔌 [DATABASE CONNECTIVITY]
# =Focus: Mongo Connection Pooling, Atlas Auth, and Collection Initialization
# =============================================================================
class MongoDBClient:
    """
    High-Fidelity Ingestor for direct Nightscout MongoDB access.
    Bypasses REST API for high-performance historical backfills and live polling.
    """
    def __init__(self):
        self.uri = config.MONGO_URI
        self.logger = logging.getLogger("Bio-Quant.Ingestion.Mongo")
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.entries = None
        self.treatments = None
        
        if not self.uri:
            self.logger.warning("MONGO_URI not configured. MongoDB ingestion disabled.")
            return

        try:
            # TLS/SSL is required for Atlas; serverSelectionTimeout ensures we don't hang
            self.client = AsyncIOMotorClient(self.uri, serverSelectionTimeoutMS=5000)
            # Nightscout default DB name is usually part of URI, but we'll ensure 'nightscout' fallback
            db_name = self.uri.split('/')[-1].split('?')[0] or "nightscout"
            self.db = self.client[db_name]
            self.entries = self.db["entries"]
            self.treatments = self.db["treatments"]
            self.logger.info(f"MongoDB client initialized for database: {db_name}")
        except Exception as e:
            self.logger.error(f"Failed to initialize MongoDB client: {e}")

# =============================================================================
# 📥 [INGESTION & DATA RETRIEVAL]
# =Focus: Real-Time Polling and Historical Backfilling (Glucose & Treatments)
# =============================================================================
    async def fetch_recent_glucose(self, count: int = 10) -> List[GlucoseReading]:
        """Fetches the latest N glucose readings (Live Mode)."""
        if self.entries is None: return []
        
        readings = []
        try:
            cursor = self.entries.find().sort("date", -1).limit(count)
            async for doc in cursor:
                reading = self._map_entry_to_reading(doc)
                if reading:
                    readings.append(reading)
        except Exception as e:
            self.logger.error(f"Error fetching recent glucose: {e}")
        
        return sorted(readings, key=lambda x: x.timestamp)

    async def fetch_since(self, start_ts: datetime) -> List[GlucoseReading]:
        """Fetches all glucose readings since a specific timestamp (Backfill Mode)."""
        if self.entries is None: return []
        
        start_ms = start_ts.timestamp() * 1000
        readings = []
        try:
            cursor = self.entries.find({"date": {"$gte": start_ms}}).sort("date", 1)
            async for doc in cursor:
                reading = self._map_entry_to_reading(doc)
                if reading:
                    readings.append(reading)
        except Exception as e:
            self.logger.error(f"Error fetching glucose since {start_ts}: {e}")
            
        return readings

    async def fetch_recent_treatments(self, hours: float = 24.0) -> List[tuple]:
        """Fetches insulin and meal events for the last N hours."""
        if self.treatments is None: return []
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        doses = []
        meals = []
        
        try:
            # Nightscout stores created_at as ISO string or Date
            cursor = self.treatments.find({
                "created_at": {"$gte": cutoff.isoformat()},
                "eventType": {"$in": ["Meal Bolus", "Correction Bolus", "Note", "Carb Correction"]}
            }).sort("created_at", 1)
            
            async for doc in cursor:
                event = self._map_treatment(doc)
                if isinstance(event, InsulinDose):
                    doses.append(event)
                elif isinstance(event, MealEvent):
                    meals.append(event)
        except Exception as e:
            self.logger.error(f"Error fetching treatments: {e}")
            
        return doses, meals

# =============================================================================
# 📊 [CLINICAL REPORTING & MAINTENANCE]
# =Focus: CSV Exports, Regional Sync, and Retention Cleanup Logic
# =============================================================================
    async def export_sensor_periods(self, output_dir: str = "data/exports", scrub_pii: bool = True):
        """
        Segments the entire history into 15-day sensor chapters and exports as CSV.
        Implements Task II core logic.
        """
        if self.entries is None: return
        
        # Ensure output directory exists
        from pathlib import Path
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        try:
            # Find boundary dates
            first_doc = await self.entries.find().sort("date", 1).limit(1).to_list(1)
            last_doc = await self.entries.find().sort("date", -1).limit(1).to_list(1)
            
            if not first_doc or not last_doc:
                self.logger.warning("No data found for export.")
                return

            start_overall = datetime.fromtimestamp(first_doc[0]["date"] / 1000.0, tz=timezone.utc)
            end_overall = datetime.fromtimestamp(last_doc[0]["date"] / 1000.0, tz=timezone.utc)
            
            self.logger.info(f"Exporting metabolic history from {start_overall.date()} to {end_overall.date()}")

            # Sliding 15-day windows from newest to oldest
            current_end = end_overall
            while current_end > start_overall:
                current_start = max(start_overall, current_end - timedelta(days=15))
                
                filename = f"[{current_start.strftime('%m-%d-%y')}_to_{current_end.strftime('%m-%d-%y')}].csv"
                file_path = Path(output_dir) / filename
                
                await self._export_period_to_csv(current_start, current_end, file_path, scrub_pii)
                
                current_end = current_start - timedelta(seconds=1) # Contiguous non-overlapping

        except Exception as e:
            self.logger.error(f"Critical error during sensor period export: {e}")

    async def sync_current_period(self, output_dir: str = "data/exports", scrub_pii: bool = True):
        """
        Calculates the active 15-day sensor window and synchronizes only that file.
        Task II Implementation.
        """
        if self.entries is None: return
        
        from pathlib import Path
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        try:
            # Anchor periods from the very first data point to maintain deterministic windows
            first_docs = await self.entries.find().sort("date", 1).limit(1).to_list(1)
            last_docs = await self.entries.find().sort("date", -1).limit(1).to_list(1)
            
            if not first_docs or not last_docs: return

            start_overall = datetime.fromtimestamp(first_docs[0]["date"] / 1000.0, tz=timezone.utc)
            end_overall = datetime.fromtimestamp(last_docs[0]["date"] / 1000.0, tz=timezone.utc)
            
            # deterministic 15-day chunks
            days_since_start = (end_overall - start_overall).days
            period_index = days_since_start // 15
            
            current_start = start_overall + timedelta(days=period_index * 15)
            # The naming convention matches export_sensor_periods for continuity
            filename = f"[{current_start.strftime('%m-%d-%y')}_to_{(current_start + timedelta(days=15)).strftime('%m-%d-%y')}].csv"
            file_path = Path(output_dir) / filename
            
            self.logger.info(f"Synchronizing active sensor period: {filename}")
            await self._export_period_to_csv(current_start, current_start + timedelta(days=15), file_path, scrub_pii)

        except Exception as e:
            self.logger.error(f"Incremental sync failed: {e}")

    async def _export_period_to_csv(self, start: datetime, end: datetime, path: "Path", scrub_pii: bool):
        """Internal helper to write a specific time-slice to CSV."""
        import csv
        
        readings = await self.fetch_since(start)
        # Filter to ensure we don't go past the 'end' of this specific chunk
        period_readings = [r for r in readings if r.timestamp <= end]
        
        if not period_readings:
            return

        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            # Header: PII scrubbing means we only keep strictly relevant metabolic signals
            writer.writerow(["timestamp_utc", "glucose_mmol_l", "trend", "source"])
            
            for r in period_readings:
                writer.writerow([
                    r.timestamp.isoformat(),
                    round(r.value, 2),
                    r.trend,
                    "clinical_scrubbed" if scrub_pii else r.source
                ])
        
        self.logger.info(f"  Generated: {path.name} ({len(period_readings)} readings)")

    async def run_retention_cleanup(self, days: int = 180):
        """
        Enforces the 180-day retention policy (Task III). 
        DELETES data strictly older than the specified threshold.
        """
        if self.db is None: return
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ms = cutoff_date.timestamp() * 1000
        
        self.logger.warning(f"RETENTION POLICY: Deleting data older than {days} days (Cutoff: {cutoff_date})")
        
        try:
            res_e = await self.entries.delete_many({"date": {"$lt": cutoff_ms}})
            # Treatments often use 'created_at' ISO string
            res_t = await self.treatments.delete_many({"created_at": {"$lt": cutoff_date.isoformat()}})
            
            self.logger.info(f"Cleanup complete. Removed {res_e.deleted_count} entries and {res_t.deleted_count} treatments.")
        except Exception as e:
            self.logger.error(f"Cleanup failed: {e}")

# =============================================================================
# 🛠️ [DOCUMENT MAPPING]
# =Focus: Translating Raw BSON to Standardized Metabolic Registry Types
# =============================================================================
    def _map_entry_to_reading(self, doc: dict) -> Optional[GlucoseReading]:
        """Maps a Nightscout entry (SGV) document to a GlucoseReading."""
        try:
            raw_val = float(doc.get("sgv", 0))
            if raw_val > 40: # Likely mg/dL
                val = raw_val / 18.0182
            else:
                val = raw_val
                
            ts = datetime.fromtimestamp(doc["date"] / 1000.0, tz=timezone.utc)
            
            return GlucoseReading(
                timestamp=ts,
                value=val,
                trend=doc.get("direction", "Flat"),
                source="mongodb"
            )
        except Exception:
            return None

    def _map_treatment(self, doc: dict):
        """Maps a Nightscout treatment document to InsulinDose or MealEvent."""
        try:
            ts_str = doc.get("created_at")
            if not ts_str: return None
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            
            insulin = doc.get("insulin")
            if insulin and float(insulin) > 0:
                return InsulinDose(
                    timestamp=ts,
                    units=float(insulin),
                    type="rapid-acting"
                )
            
            carbs = doc.get("carbs")
            if carbs and float(carbs) > 0:
                return MealEvent(
                    timestamp=ts,
                    carbs=float(carbs),
                    gi_type="STARCH"
                )
        except Exception:
            return None
        return None
