import pandas as pd
from pathlib import Path
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from diabetic.config import config
from diabetic.registry import GlucoseReading, InsulinDose, MealEvent, EnvironmentReading
from diabetic.utils.db import db_manager

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
        self.logger = logging.getLogger("Bio-Quant.Ingestion.Mongo")
        self.db_manager = db_manager
        
        # Reference collections from singleton
        self.entries = self.db_manager.entries
        self.treatments = self.db_manager.treatments
        self.environment_history = self.db_manager.environment_history
        
        if self.db_manager.entries is None:
            self.logger.warning("MongoDB Singleton not initialized or entries collection missing. Ingestion limited.")

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

    async def fetch_neural_window(self) -> List[GlucoseReading]:
        """
        Specifically fetches the last 288 readings (24 hours) to ensure a full 
        circadian context and guaranteed 30-snapshot buffer for the Neural Engine.
        """
        return await self.fetch_recent_glucose(count=288)

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

    async def fetch_recent_treatments(self, count: int = 10, hours: float = 4.0) -> tuple:
        """
        Fetches the latest insulin and meal events for the last N hours.
        Returns Tuple[Optional[InsulinDose], Optional[MealEvent]] to match
        the NightscoutClient contract and prevent arity mismatch in coordinator.
        """
        if self.treatments is None:
            return None, None
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        latest_insulin: Optional[InsulinDose] = None
        latest_meal: Optional[MealEvent] = None
        
        try:
            # Nightscout stores created_at as ISO string or Date
            cursor = self.treatments.find({
                "created_at": {"$gte": cutoff.isoformat()},
                "eventType": {"$in": ["Meal Bolus", "Correction Bolus", "Note", "Carb Correction"]}
            }).sort("created_at", -1).limit(count*2)  # Most recent first so we grab the latest
            
            async for doc in cursor:
                insulin_event, meal_event = self._map_treatment(doc)
                if isinstance(insulin_event, InsulinDose) and not latest_insulin:
                    latest_insulin = insulin_event
                if isinstance(meal_event, MealEvent) and not latest_meal:
                    latest_meal = meal_event
                # Stop early once both slots are filled
                if latest_insulin and latest_meal:
                    break
        except Exception as e:
            self.logger.error(f"Error fetching treatments: {e}")
            
        return latest_insulin, latest_meal

    async def save_environment_reading(self, reading: EnvironmentReading):
        """Persists environmental context for historical anchoring (Phase 3)."""
        if self.environment_history is None: return
        
        try:
            doc = {
                "timestamp": reading.timestamp,
                "temperature": reading.temperature,
                "humidity": reading.humidity,
                "aqi": reading.aqi
            }
            await self.environment_history.insert_one(doc)
        except Exception as e:
            self.logger.error(f"Failed to save environment reading: {e}")

# =============================================================================
# 📊 [TRAINING & CLINICAL ANALYSIS]
# =Focus: High-Volume Data Retrieval for Model Optimization
# =============================================================================
    async def fetch_training_data(self, days: int = 15) -> Optional[pd.DataFrame]:
        """
        Retrieves joined glucose and treatment data for a training window.
        Returns a Pandas DataFrame formatted for MetabolicDataset.
        """
        if self.entries is None:
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        start_ms = cutoff.timestamp() * 1000

        try:
            self.logger.info(f"Fetching training data for the last {days} days...")
            
            # 1. Fetch Glucose (Entries)
            entries_cursor = self.entries.find({"date": {"$gte": start_ms}}).sort("date", 1)
            entries_raw = await entries_cursor.to_list(length=10000)
            
            if not entries_raw:
                self.logger.warning("No glucose entries found for training window.")
                return None

            df_entries = pd.DataFrame([{
                "timestamp": datetime.fromtimestamp(d["date"] / 1000.0, tz=timezone.utc),
                "glucose": float(d.get("sgv", 0)) / 18.0182 if float(d.get("sgv", 0)) > 40 else float(d.get("sgv", 0)),
                "trend": d.get("direction", "Flat")
            } for d in entries_raw])

            # 2. Fetch Treatments (Bolus/Meals)
            # Treatments use ISO date strings in NS, but we query by created_at
            treatments_cursor = self.treatments.find({
                "created_at": {"$gte": cutoff.isoformat()}
            }).sort("created_at", 1)
            treatments_raw = await treatments_cursor.to_list(length=5000)

            if treatments_raw:
                df_treatments = pd.DataFrame([{
                    "timestamp": datetime.fromisoformat(t["created_at"].replace('Z', '+00:00')),
                    "bolus": float(t.get("insulin", 0)) if t.get("insulin") else 0,
                    "meal": float(t.get("carbs", 0)) if t.get("carbs") else 0
                } for t in treatments_raw])
                
                # Merge logic: align treatments to the nearest glucose reading
                # Note: This is a simplified merge, MetabolicDataset will resample
                df = pd.merge_asof(
                    df_entries.sort_values("timestamp"),
                    df_treatments.sort_values("timestamp"),
                    on="timestamp",
                    direction="backward",
                    tolerance=timedelta(minutes=5)
                )
            else:
                df = df_entries
                df["bolus"] = 0
                df["meal"] = 0

            df = df.fillna(0)

            # 3. Fetch Environment (Weather) - Anchor Step
            env_cursor = self.environment_history.find({"timestamp": {"$gte": cutoff}})
            env_raw = await env_cursor.to_list(length=5000)
            if env_raw:
                df_env = pd.DataFrame([{
                    "timestamp": e["timestamp"],
                    "temperature": e.get("temperature", 25.0),
                    "humidity": e.get("humidity", 60.0),
                    "aqi": e.get("aqi", 50.0)
                } for e in env_raw])
                
                # Merge logic (deterministic anchor)
                df = pd.merge_asof(
                    df.sort_values("timestamp"),
                    df_env.sort_values("timestamp"),
                    on="timestamp",
                    direction="backward",
                    tolerance=timedelta(minutes=60) # 1-hour anchor window
                )
            
            # Fill missing weather with Baseline (Regional Hanoi)
            df['temperature'] = df['temperature'].fillna(26.5)
            df['humidity'] = df['humidity'].fillna(80.0)
            df['aqi'] = df['aqi'].fillna(45.0)

            self.logger.info(f"Successfully retrieved {len(df)} training samples from MongoDB (Anchored with Env).")
            return df

        except Exception as e:
            self.logger.error(f"Failed to fetch training data from MongoDB: {e}")
            return None

# =============================================================================
# 📊 [CLINICAL REPORTING & MAINTENANCE]
# =Focus: CSV Exports, Regional Sync, and Retention Cleanup Logic
# =============================================================================
    async def export_sensor_periods(self, output_dir: str = "storage/exports", scrub_pii: bool = True):
        """
        Segments the entire history into 15-day sensor chapters and exports as CSV.
        Implements Task II core logic.
        """
        if self.entries is None: return
        
        # Ensure output directory exists
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

    async def sync_current_period(self, output_dir: str = "storage/exports", scrub_pii: bool = True):
        """
        Calculates the active 15-day sensor window and synchronizes only that file.
        Task II Implementation.
        """
        if self.entries is None: return
        
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
        """Internal helper to write a specific time-slice to CSV using optimized native queries."""
        import csv
        
        if self.entries is None: return
        
        start_ms = start.timestamp() * 1000
        end_ms = end.timestamp() * 1000
        
        readings = []
        try:
            # OPTIMIZED: pass date range to MongoDB query instead of Python filtering
            cursor = self.entries.find({
                "date": {"$gte": start_ms, "$lte": end_ms}
            }).sort("date", 1)
            
            async for doc in cursor:
                reading = self._map_entry_to_reading(doc)
                if reading:
                    readings.append(reading)
        except Exception as e:
            self.logger.error(f"Query optimization failure unexpectedly in export: {e}")
            return
        
        if not readings:
            return

        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            # Header: PII scrubbing means we only keep strictly relevant metabolic signals
            writer.writerow(["timestamp_utc", "glucose_mmol_l", "trend", "source"])
            
            for r in readings:
                writer.writerow([
                    r.timestamp.isoformat(),
                    round(r.value, 2),
                    r.trend,
                    "clinical_scrubbed" if scrub_pii else r.source
                ])
        
        self.logger.info(f"  Generated: {path.name} ({len(readings)} readings)")

    async def run_retention_cleanup(self, days: int = 180):
        """
        Enforces the 180-day retention policy (Task III). 
        DELETES data strictly older than the specified threshold.
        """
        # Fix C1: self.db does not exist; guard against actual collection references.
        if self.entries is None or self.treatments is None: return
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_ms = cutoff_date.timestamp() * 1000
        
        self.logger.warning(f"RETENTION POLICY: Deleting data older than {days} days (Cutoff: {cutoff_date})")
        
        try:
            res_e = await self.entries.delete_many({"date": {"$lt": cutoff_ms}})
            # FIX D5: Pass datetime object directly — NOT .isoformat() string.
            # String comparison fails on non-zero-padded Nightscout dates (e.g., 2024-3-5T...).
            # Motor/PyMongo correctly serializes datetime to BSON Date for comparison.
            res_t = await self.treatments.delete_many({"created_at": {"$lt": cutoff_date}})
            
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
        """Maps a Nightscout treatment document to optional insulin and meal events."""
        try:
            ts_str = doc.get("created_at")
            if not ts_str:
                return None, None
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))

            insulin_event = None
            meal_event = None
            insulin = doc.get("insulin")
            if insulin and float(insulin) > 0:
                insulin_event = InsulinDose(
                    timestamp=ts,
                    units=float(insulin),
                    type="rapid-acting"
                )

            carbs = doc.get("carbs")
            if carbs and float(carbs) > 0:
                meal_event = MealEvent(
                    timestamp=ts,
                    carbs=float(carbs),
                    gi_type="STARCH"
                )
            return insulin_event, meal_event
        except Exception:
            return None, None
