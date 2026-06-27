"""
diabetic/auth/dependencies.py

FastAPI auth dependency for the TWA bridge. Reads the `Authorization` header:
    Authorization: tma <initData>     -> verified Telegram Mini App identity
    Authorization: dev <token>        -> dev bypass, only when config.TWA_DEV_TOKEN set
then authorizes against patient/caregiver/registry. Raises 401/403.
"""
import hmac
import logging

from fastapi import Header, HTTPException

from diabetic.auth.authorization import is_authorized
from diabetic.auth.telegram_webapp import InitDataError, validate_init_data

logger = logging.getLogger("Bio-Quant.Auth")


async def require_twa_user(authorization: str = Header(default="")) -> dict:
    """Guard dependency; returns the authenticated Telegram user dict."""
    from diabetic.config import config
    from diabetic.telegram_bot import twa_api  # lazy: COORDINATOR_REF lives there

    scheme, _, credential = authorization.partition(" ")
    scheme = scheme.lower().strip()
    credential = credential.strip()

    if not scheme or not credential:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Dev bypass for plain-browser testing (disabled unless TWA_DEV_TOKEN is set).
    if scheme == "dev":
        if config.TWA_DEV_TOKEN and hmac.compare_digest(credential, config.TWA_DEV_TOKEN):
            return {"id": int(config.USER_ID), "first_name": "Dev", "dev": True}
        raise HTTPException(status_code=401, detail="Invalid dev token")

    if scheme != "tma":
        raise HTTPException(status_code=401, detail="Unsupported auth scheme")

    try:
        user = validate_init_data(
            credential, config.TELEGRAM_TOKEN, config.TWA_AUTH_MAX_AGE_SECS
        )
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=f"Invalid Telegram initData: {e}")

    coordinator = getattr(twa_api, "COORDINATOR_REF", None)
    if not await is_authorized(user["id"], coordinator):
        logger.warning("TWA auth: user %s is not patient/caregiver", user.get("id"))
        raise HTTPException(status_code=403, detail="Not an authorized patient or caregiver")

    return user
