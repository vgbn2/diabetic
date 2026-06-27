"""
Contract tests for the Telegram WebApp auth surface (diabetic/auth/).

Security-critical and loop-free: initData is signed with a test bot token using
the exact Telegram algorithm, then validated. Tampered payloads, wrong tokens,
stale timestamps, and missing fields must all be rejected.
"""
import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

from diabetic.auth import authorization as A
from diabetic.auth.telegram_webapp import InitDataError, validate_init_data

BOT_TOKEN = "123456:TEST-bot-token-abc"


def _sign(fields: dict, token: str = BOT_TOKEN) -> str:
    """Build a signed initData query string the way Telegram does."""
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def _fields(uid: int = 111, auth_date: float = None) -> dict:
    return {
        "auth_date": str(int(auth_date if auth_date is not None else time.time())),
        "query_id": "AAEoo",
        "user": json.dumps({"id": uid, "first_name": "Pat"}, separators=(",", ":")),
    }


class TestInitDataValidation(unittest.TestCase):
    def test_valid_passes_and_returns_user(self):
        data = _sign(_fields(uid=111))
        user = validate_init_data(data, BOT_TOKEN, 86400)
        self.assertEqual(user["id"], 111)
        self.assertEqual(user["first_name"], "Pat")

    def test_tampered_payload_rejected(self):
        data = _sign(_fields(uid=111))
        tampered = data.replace("Pat", "Eve")  # change a signed field, keep old hash
        with self.assertRaises(InitDataError):
            validate_init_data(tampered, BOT_TOKEN, 86400)

    def test_wrong_bot_token_rejected(self):
        data = _sign(_fields(uid=111), token="999999:DIFFERENT")
        with self.assertRaises(InitDataError):
            validate_init_data(data, BOT_TOKEN, 86400)

    def test_stale_auth_date_rejected(self):
        data = _sign(_fields(uid=111, auth_date=time.time() - 100000))
        with self.assertRaises(InitDataError):
            validate_init_data(data, BOT_TOKEN, 86400)

    def test_missing_hash_rejected(self):
        with self.assertRaises(InitDataError):
            validate_init_data("auth_date=1&user=%7B%7D", BOT_TOKEN, 86400)

    def test_empty_rejected(self):
        with self.assertRaises(InitDataError):
            validate_init_data("", BOT_TOKEN, 86400)


def _run(coro):
    """Drive a coroutine with no real awaits (loop-free) and return its value."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise AssertionError("coroutine awaited unexpectedly")


class TestAuthorization(unittest.TestCase):
    def test_patient_and_caregiver_allowed_others_denied(self):
        with patch.object(A, "_static_allowlist", return_value={111, 222}):
            self.assertTrue(_run(A.is_authorized(111)))   # patient
            self.assertTrue(_run(A.is_authorized(222)))   # caregiver
            self.assertFalse(_run(A.is_authorized(333)))  # stranger
            self.assertFalse(_run(A.is_authorized(None)))


if __name__ == "__main__":
    unittest.main()
