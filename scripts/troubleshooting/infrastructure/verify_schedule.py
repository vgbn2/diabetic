from datetime import datetime, timezone, time
from diabetic.utils.schedule import schedule_manager
from diabetic.ml_engine.twin import DigitalTwin

def test_schedule_logic():
    print("\n--- SCHEDULE LOGIC VERIFICATION ---")
    
    # Test Time 1: 3:00 AM (Monday) - Should be SLEEP (Indoor, 1.1x Resistance)
    t1 = datetime(2026, 4, 13, 3, 0, tzinfo=timezone.utc)
    event1 = schedule_manager.get_event_at(t1)
    
    twin = DigitalTwin()
    mult1 = twin.get_hormonal_multiplier(t1)
    
    print(f"Time: {t1.strftime('%H:%M')} | Event: {event1.name if event1 else 'None'}")
    print(f"Resistance Multiplier: {mult1:.4f} (Expected increase due to Sleep)")
    
    # Test Time 2: 8:30 AM (Monday) - Should be COMMUTE (Outdoor)
    t2 = datetime(2026, 4, 13, 8, 30, tzinfo=timezone.utc)
    event2 = schedule_manager.get_event_at(t2)
    print(f"Time: {t2.strftime('%H:%M')} | Event: {event2.name if event2 else 'None'} | Outdoor: {event2.is_outdoor}")
    
    # Test Time 3: 7:00 PM (Monday) - Should be GYM (0.8x Resistance / High Sensitivity)
    t3 = datetime(2026, 4, 13, 19, 0, tzinfo=timezone.utc)
    event3 = schedule_manager.get_event_at(t3)
    mult3 = twin.get_hormonal_multiplier(t3)
    
    print(f"Time: {t3.strftime('%H:%M')} | Event: {event3.name if event3 else 'None'}")
    print(f"Resistance Multiplier: {mult3:.4f} (Expected decrease due to Workout)")

    print("\n--- CONCLUSION ---")
    if event1.type == "SLEEP" and event2.is_outdoor and event3.type == "WORKOUT":
        print("STATUS: SUCCESS - Schedule is overriding heuristics correctly.")
    else:
        print("STATUS: FAILED - Checks did not match expected JSON patterns.")

if __name__ == "__main__":
    test_schedule_logic()
