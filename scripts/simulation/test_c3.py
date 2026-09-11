import asyncio
import pytest
from diabetic.utils.audit_logger import AuditLogger
from diabetic.telegram_bot.decision_matrix import FeedbackEngine

@pytest.mark.asyncio
async def test(tmp_path):
    logger = AuditLogger(local_db_path=str(tmp_path / "audit.db"))
    try:
        await logger.log_feedback('STRESS_ANOMALY', 'false_alarm')
        await logger.log_feedback('STRESS_ANOMALY', 'false_alarm')
        await logger.log_feedback('STRESS_ANOMALY', 'false_alarm')
        
        dampener = await FeedbackEngine.get_dampener(logger, 'STRESS_ANOMALY')
        print(f'[C3-VERIFY] STRESS_ANOMALY Dampener after 3 False Alarms: {dampener}')
        assert dampener == 1.4, f'Expected 1.4, got {dampener}'
    finally:
        logger.local_conn.close()
        print('[C3-VERIFY] RLHF Loop verified with isolated temp DB.')

if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(test(Path(tmp)))
