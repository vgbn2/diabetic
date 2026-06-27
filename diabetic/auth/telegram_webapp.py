"""
diabetic/auth/telegram_webapp.py

Validate Telegram Mini App (Web App) `initData` server-side.
Spec: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Algorithm:
    data_check_string = "\\n".join(sorted "key=value", excluding `hash`)
    secret_key        = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
    expected_hash     = HMAC_SHA256(key=secret_key,   msg=data_check_string)
    valid  <=>  expected_hash == provided hash   (constant-time compare)
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InitDataError(ValueError):
    """Raised when initData is missing, malformed, tampered, or stale."""


def validate_init_data(init_data: str, bot_token: str, max_age_secs: int = 86400) -> dict:
    """
    Verify a Telegram Mini App `initData` query string and return the parsed
    `user` dict. Raises InitDataError on any failure.
    """
    if not init_data:
        raise InitDataError("empty initData")
    if not bot_token:
        raise InitDataError("server bot token not configured")

    # parse_qsl decodes percent-encoding; Telegram signs the DECODED values.
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("missing hash")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("hash mismatch (tampered payload or wrong bot token)")

    # Freshness (replay protection)
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise InitDataError("invalid auth_date")
    if max_age_secs > 0 and auth_date > 0:
        age = time.time() - auth_date
        if age > max_age_secs:
            raise InitDataError(f"initData expired ({int(age)}s > {max_age_secs}s)")

    # User payload
    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataError("missing user")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        raise InitDataError("invalid user JSON")
    if "id" not in user:
        raise InitDataError("user has no id")
    return user
