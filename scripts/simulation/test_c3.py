import asyncio
from diabetic.utils.audit_logger import AuditLogger
from diabetic.telegram_bot.decision_matrix import FeedbackEngine

async def test():
    logger = AuditLogger()
    await logger.log_feedback('STRESS_ANOMALY', 'false_alarm')
    await logger.log_feedback('STRESS_ANOMALY', 'false_alarm')
    await logger.log_feedback('STRESS_ANOMALY', 'false_alarm')
    
    dampener = await FeedbackEngine.get_dampener(logger, 'STRESS_ANOMALY')
    print(f'[C3-VERIFY] STRESS_ANOMALY Dampener after 3 False Alarms: {dampener}')
    assert dampener == 1.4, f'Expected 1.4, got {dampener}'

    cursor = logger.local_conn.cursor()
    cursor.execute("DELETE FROM audit_logs WHERE event_type='USER_FEEDBACK'")
    logger.local_conn.commit()
    print('[C3-VERIFY] RLHF Loop verified and cleaned up.')

asyncio.run(test())
