"""
diabetic/auth/authorization.py

Shared authorization check for Bio-Quant surfaces. Mirrors the bot's
restrict_access (telegram_bot/handlers.py): the patient (`config.USER_ID`) and
an optional caregiver (`config.CAREGIVER_ID`) are always allowed; any user
present in the VesselRegistry is also allowed when a coordinator is supplied.
"""
import logging

logger = logging.getLogger("Bio-Quant.Auth")


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
    True if `user_id` is the patient, the caregiver, or a registered user.
    The static allowlist is checked first (no I/O); the registry is consulted
    only when a coordinator with a `vessel_registry` is provided.
    """
    if user_id is None:
        return False
    uid = int(user_id)

    if uid in _static_allowlist():
        return True

    if coordinator is not None and hasattr(coordinator, "vessel_registry"):
        try:
            reg_user = await coordinator.vessel_registry.get_user(uid)
            return reg_user is not None
        except Exception as e:  # noqa: BLE001 — auth must fail closed, not crash
            logger.debug("registry auth check failed for %s: %s", uid, e)
            return False

    return False
