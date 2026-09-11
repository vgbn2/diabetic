import hashlib
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import diabetic.ingestion.nightscout as ns_module
from diabetic.ingestion.nightscout import NightscoutClient


def _make_client(secret: str = "short", url: str = "http://mock.local") -> NightscoutClient:
    """Instantiate NightscoutClient with a patched config."""
    with patch.object(ns_module, "config") as cfg:
        cfg.API_SECRET = secret
        cfg.NIGHTSCOUT_URL = url
        cfg.PREFER_MMOL = True
        cfg.SAMPLING_INTERVAL_MINS = 5
        return NightscoutClient()


def _make_401_error() -> httpx.HTTPStatusError:
    mock_response = MagicMock()
    mock_response.status_code = 401
    return httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=mock_response)


class TestNightscoutAuthScrubbing(unittest.TestCase):

    def test_short_secret_not_stored_as_token(self):
        """Short/plain secrets must be stored as a hash only, never as a token."""
        client = _make_client(secret="shortpassword")
        self.assertIsNone(client._token)
        self.assertFalse(client._is_token_mode)
        self.assertEqual(client.hashed_secret, hashlib.sha1("shortpassword".encode()).hexdigest())

    def test_long_dash_token_stored(self):
        """Opaque access tokens (long with dashes) must be stored as the raw token."""
        secret = "subject-long-access-token-with-dashes"
        client = _make_client(secret=secret)
        self.assertEqual(client._token, secret)
        self.assertTrue(client._is_token_mode)

    def test_subject_prefix_triggers_token_mode(self):
        """Secrets starting with 'subject-' are always treated as tokens."""
        secret = "subject-abc"
        client = _make_client(secret=secret)
        self.assertTrue(client._is_token_mode)

    def test_raw_secret_not_stored_on_self(self):
        """The raw secret must not be accessible as any attribute on the client."""
        client = _make_client(secret="anyvalue123")
        self.assertFalse(hasattr(client, "_raw"))
        self.assertFalse(hasattr(client, "raw_secret"))
        self.assertFalse(hasattr(client, "secret"))


class TestNightscoutAuthRetry(unittest.IsolatedAsyncioTestCase):

    async def test_401_flips_mode_and_retries(self):
        """On 401 with token auth, _is_token_mode must flip to False and the call retried."""
        client = _make_client(secret="subject-long-access-token")

        call_count = 0

        async def _mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_401_error()
            # Second call succeeds with empty entries list
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = []
            return mock_resp

        client.client.get = _mock_get

        result = await client.fetch_recent_glucose(5)

        self.assertFalse(client._is_token_mode, "Mode should flip to False after 401")
        self.assertEqual(call_count, 2, "Should have made exactly 2 HTTP calls")
        self.assertEqual(result, [])

    async def test_fetch_treatments_returns_data_after_401(self):
        """
        R1 regression gate: fetch_recent_treatments must NOT discard the
        fallback response. After a 401, treatment data must be returned.
        """
        client = _make_client(secret="subject-long-access-token")

        # Treatment timestamp within the 4-hour metabolic window
        ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")

        call_count = 0

        async def _mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_401_error()
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = [
                {"created_at": ts, "insulin": "5.0", "eventType": "Correction Bolus"}
            ]
            return mock_resp

        client.client.get = _mock_get

        result = await client.fetch_recent_treatments(5)

        self.assertGreater(
            len(result.insulin), 0,
            "R1 regression: treatment data was silently dropped on 401 fallback"
        )
        self.assertEqual(result.state, "ok")
        self.assertEqual(result.insulin[0].units, 5.0)

    async def test_auth_retry_exhaustion_raises_not_none(self):
        """
        R6 regression gate: if the first 401 lands on the final attempt (after two
        transient failures), the retry helper must raise — never fall through to
        None, which would crash callers via None.json() (AttributeError).
        """
        client = _make_client(secret="subject-long-access-token")

        call_count = 0

        async def _mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("transient")  # attempts 0,1 -> generic except -> sleep
            raise _make_401_error()  # attempt 2 -> 401 in token mode -> continue -> loop ends

        client.client.get = _mock_get

        with patch("asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(RuntimeError):
                await client.fetch_recent_glucose(5)

    async def test_access_probe_classifies_authenticated_outcomes(self):
        cases = [
            (200, "ok"),
            (401, "rejected"),
            (403, "rejected"),
            (404, "unreachable"),
            (429, "rate_limited"),
            (500, "unreachable"),
        ]
        for status_code, expected in cases:
            with self.subTest(status_code=status_code):
                client = _make_client(secret="short")
                response = MagicMock()
                response.status_code = status_code
                if status_code == 200:
                    response.raise_for_status.return_value = None
                else:
                    response.raise_for_status.side_effect = httpx.HTTPStatusError(
                        str(status_code), request=MagicMock(), response=response
                    )
                client.client.get = AsyncMock(return_value=response)

                with patch("asyncio.sleep", new=AsyncMock()):
                    result = await client.probe_access()
                await client.close()

                self.assertEqual(result.state, expected)
                if status_code != 200:
                    self.assertNotIn("short", result.reason or "")

    async def test_access_probe_uses_initialized_credential_state(self):
        client = _make_client(secret="short")
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        client.client.get = AsyncMock(return_value=response)

        with patch.object(ns_module.config, "API_SECRET", ""):
            result = await client.probe_access()
        await client.close()

        self.assertEqual(result.state, "ok")

    async def test_access_probe_reports_misconfigured_without_request(self):
        client = _make_client(secret="", url="")
        client.client.get = AsyncMock()

        result = await client.probe_access()
        await client.close()

        self.assertEqual(result.state, "misconfigured")
        client.client.get.assert_not_awaited()

    async def test_non_401_error_returns_degraded_result(self):
        """Provider failure must not masquerade as a valid empty result."""
        client = _make_client(secret="short")

        async def _mock_get(*args, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            raise httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)

        client.client.get = _mock_get

        result = await client.fetch_recent_treatments(5)
        self.assertEqual(result.state, "degraded")
        self.assertEqual(result.insulin, [])
        self.assertEqual(result.meals, [])
        self.assertEqual(result.error_reason, "HTTPStatusError")


if __name__ == "__main__":
    unittest.main()
