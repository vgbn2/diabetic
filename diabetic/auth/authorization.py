"""
diabetic/auth/authorization.py

Shared authorization check for Bio-Quant surfaces. The current runtime owns one
patient pipeline, so only the patient (`config.USER_ID`) and optional caregiver
(`config.CAREGIVER_ID`) may access it. VesselRegistry membership is storage
state, not an authorization grant.
"""

def _static_allowlist() -> set:
    """Patient + caregiver Telegram IDs from config (non-zero only)."""
    from diabetic.config import config

    allowed = set()
    if config.USER_ID:
        allowed.add(int(config.USER_ID))
    if config.CAREGIVER_ID:
        allowed.add(int(config.CAREGIVER_ID))
    return allowed


async def is_authorized(user_id, coordinator=None) -> bool:
    """
    True only when `user_id` is the configured patient or caregiver.

    `coordinator` remains accepted for caller compatibility, but registry rows
    never authorize access to the singleton patient's data.
    """
    if user_id is None:
        return False
    try:
        return int(user_id) in _static_allowlist()
    except (TypeError, ValueError):
        return False
