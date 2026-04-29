import logging
from datetime import datetime, timezone
try:
    import holidays
except ImportError:
    holidays = None

from diabetic import medical_constants as mc
from diabetic.config import config

# =============================================================================
# 🌍 [TEMPORAL CONTEXT INITIALIZATION]
# =Focus: Regional Holiday Discovery and Festival Registration
# =============================================================================
class TemporalEngine:
    """
    Layer 2: Adaptive Regimes (Temporal Context).
    Refines metabolic resistance multipliers based on routine (weekdays) 
    vs non-routine (weekends/holidays) states.
    """
    def __init__(self):
        self.logger = logging.getLogger("diabetic.temporal")
        self._holiday_cache = {}
        
        # High-Social Eating Festivals (Tier 4: +20%)
        self.festivals = [
            "Tết", "Tet", "Hung Kings", "Liberation Day", "Chiến thắng", "Quốc khánh", "National Day"
        ]
        
        # Sugar-Aggressive Events (Tier 4 overrides)
        # FIX M5: Gate on specific year for lunar festivals
        self.sugar_events = {
            (2026, 9, 25): "Mid-Autumn Festival"
        }

    def _get_holidays(self, year: int):
        """Lazy-loads and caches holidays for a specific year (Fix H2)."""
        if year not in self._holiday_cache:
            if holidays:
                try:
                    self._holiday_cache[year] = holidays.Vietnam(years=year)
                except Exception as e:
                    self.logger.error(f"Failed to initialize holidays for {year}: {e}")
                    self._holiday_cache[year] = None
            else:
                self._holiday_cache[year] = None
        return self._holiday_cache[year]

# =============================================================================
# ⚙️ [METABOLIC MULTIPLIER REGISTRY]
# =Focus: Routine vs Non-Routine resistance logic and Social Overrides
# =============================================================================
    def get_multiplier(self, dt: "Optional[datetime]" = None) -> float:#experimental,psuedo scienece
        """
        Returns the metabolic resistance multiplier based on the day's context.
        ROUTINE: 1.0 (Weekday)
        WEEKEND: 1.05 (+5%)
        HOLIDAY: 1.10 (+10%)
        FESTIVAL: 1.20 (+20%)
        """
        if dt is None:
            dt = datetime.now(timezone.utc)
            
        # 1. Baseline: Routine Weekday
        multiplier = 1.0
        
        # 2. Weekend Check (+5%)
        if dt.weekday() >= 5:
            multiplier = mc.WEEKEND_RESISTANCE_MULT
            
        # 3. Holiday/Festival Check (Fix H2)
        vn_h = self._get_holidays(dt.year)
        if vn_h:
            holiday_name = vn_h.get(dt)
            if holiday_name:
                # Check for high-impact social festivals (+20%)
                if any(fest in holiday_name for fest in self.festivals):
                    multiplier = mc.FESTIVAL_RESISTANCE_MULT
                else:
                    # Standard holiday rest day (+10%)
                    multiplier = mc.HOLIDAY_RESISTANCE_MULT

        # 4. Custom Sugar Event Override (Fix M5: Year-aware)
        event_key = (dt.year, dt.month, dt.day)
        if event_key in self.sugar_events:
            multiplier = mc.FESTIVAL_RESISTANCE_MULT
            
        return multiplier

# Singleton instance
temporal_engine = TemporalEngine()
