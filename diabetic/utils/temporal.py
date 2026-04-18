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
        self.vn_holidays = None
        if holidays:
            try:
                # Initialize with Vietnamese registry based on config
                self.vn_holidays = holidays.Vietnam(years=datetime.now().year)
            except Exception as e:
                self.logger.error(f"Failed to initialize holidays library: {e}")

        # High-Social Eating Festivals (Tier 4: +20%)
        #is there a library for these type of festivals, at somepoint other countries festivals is needed in here also
        self.festivals = [
            "Tết", "Tet", "Hung Kings", "Liberation Day", "Chiến thắng", "Quốc khánh", "National Day"
        ]
        
        # Sugar-Aggressive Events (Tier 4 overrides)
        # Mid-Autumn 2026: Sept 25. High Mooncake sugar load.
        #add tet and other food related festival also
        self.sugar_events = {
            (9, 25): "Mid-Autumn Festival"
        }

# =============================================================================
# ⚙️ [METABOLIC MULTIPLIER REGISTRY]
# =Focus: Routine vs Non-Routine resistance logic and Social Overrides
# =============================================================================
    def get_multiplier(self, dt: "Optional[datetime]" = None) -> float:
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
            
        # 3. Holiday/Festival Check
        if self.vn_holidays:
            holiday_name = self.vn_holidays.get(dt)
            if holiday_name:
                # Check for high-impact social festivals (+20%)
                if any(fest in holiday_name for fest in self.festivals):
                    multiplier = mc.FESTIVAL_RESISTANCE_MULT
                else:
                    # Standard holiday rest day (+10%)
                    multiplier = mc.HOLIDAY_RESISTANCE_MULT

        # 4. Custom Sugar Event Override (+20% for Mid-Autumn/etc)
        event_key = (dt.month, dt.day)
        if event_key in self.sugar_events:
            multiplier = mc.FESTIVAL_RESISTANCE_MULT
            
        return multiplier

# Singleton instance
temporal_engine = TemporalEngine()
