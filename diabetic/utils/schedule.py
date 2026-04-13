import json
from datetime import datetime, time, date
from pathlib import Path
from typing import Optional, List, Dict, Any
from diabetic.registry import ScheduleEvent

class ScheduleManager:
    """
    Manages user schedules, including recurring weekly events and one-off overrides.
    Central 'Truth Source' for behavioral context.
    """
    
    def __init__(self, schedule_path: str = "data/schedules/user_schedule.json"):
        self.path = Path(schedule_path)
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self):
        if not self.path.exists():
            self.data = {"recurring": [], "overrides": []}
            return
        with open(self.path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

    def _time_in_range(self, start: time, end: time, x: time) -> bool:
        """Handles overnight ranges (e.g., 22:00 to 07:00)."""
        if start <= end:
            return start <= x <= end
        else:
            return x >= start or x <= end

    def get_event_at(self, dt: datetime) -> Optional[ScheduleEvent]:
        """
        Returns the active schedule event for a given timestamp.
        Priority: 1. Overrides (Date specific) -> 2. Recurring (Weekly)
        """
        current_time = dt.time()
        current_date = dt.date()
        current_weekday = dt.weekday() # 0 = Monday

        # 1. Check Overrides
        for entry in self.data.get("overrides", []):
            if entry.get("date") == current_date.isoformat():
                start = time.fromisoformat(entry["start"])
                end = time.fromisoformat(entry["end"])
                if self._time_in_range(start, end, current_time):
                    return ScheduleEvent(**entry)

        # 2. Check Recurring
        for entry in self.data.get("recurring", []):
            if current_weekday in entry.get("days", []):
                start = time.fromisoformat(entry["start"])
                end = time.fromisoformat(entry["end"])
                if self._time_in_range(start, end, current_time):
                    return ScheduleEvent(**entry)

        return None

# Singleton instance
schedule_manager = ScheduleManager()
