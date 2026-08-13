import httpx
import hashlib
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Literal, Optional
from diabetic.registry import (
    GlucoseReading,
    InsulinDose,
    MealEvent,
    TreatmentFetchResult,
)
from diabetic.config import config
from diabetic import medical_constants
from diabetic.ingestion.normalization import normalize_nightscout_sgv

AccessState = Literal[
    "ok", "rejected", "rate_limited", "misconfigured", "unreachable"
]


@dataclass(frozen=True)
class NightscoutAccessResult:
    state: AccessState
    reason: Optional[str] = None


class NightscoutClient:
    """
    Resilient bridge to the Nightscout API.
    Handles authentication, units detection, and automatic retries.
    """
    def __init__(self):
        self.url = config.NIGHTSCOUT_URL.rstrip('/')
        # FIX S6: Never store raw secret as instance attribute.
        # Compute all auth artifacts immediately and let the plaintext go out of scope.
        # This prevents secret leakage through repr(), tracebacks, or memory dumps.
        _raw = config.API_SECRET
        self.has_credentials = bool(_raw)
        self.hashed_secret = hashlib.sha1(_raw.encode()).hexdigest()
        # Detect token mode (long access tokens with dashes vs short hashed passwords)
        self._is_token_mode = len(_raw) > 24 or '-' in _raw or _raw.startswith("subject-")
        # Store raw only if it's an opaque token (needed for Bearer / query-param auth)
        # Otherwise the hash is sufficient — do NOT store the plaintext form.
        self._token = _raw if self._is_token_mode else None
        # _raw intentionally goes out of scope here — not stored on self.
        
        # Wave 3 Hardening: Persistent AsyncClient to prevent connection exhaustion
        self.client = httpx.AsyncClient(timeout=15.0)
        self.logger = logging.getLogger("Bio-Quant.Ingestion.Nightscout")

    async def close(self):
        """Closes the underlying HTTP client."""
        await self.client.aclose()
        
    def _get_headers(self) -> dict:
        """Returns base Accept headers (no auth — auth injected via params or header below)."""
        return {"Accept": "application/json"}

    def _get_auth_params(self) -> dict:
        """
        Returns auth as query params for Heroku-hosted Nightscout instances.
        Uses token= param when secret looks like an access token (not a raw password).
        """
        if self._is_token_mode:
            return {"token": self._token}
        return {}

    def _get_auth_headers(self) -> dict:
        """Returns auth headers for instances that support header-based auth."""
        headers = {"Accept": "application/json"}
        if self._is_token_mode:
            headers["Authorization"] = f"Bearer {self._token}"
        else:
            headers["api-secret"] = self.hashed_secret
        return headers

    async def _request_with_auth_retry(self, endpoint: str, base_params: dict) -> httpx.Response:
        """
        GET request with up to 3 attempts, exponential backoff, and automatic
        401 fallback from token auth to api-secret mode.
        Auth params/headers are recomputed each attempt so the flip takes effect immediately.
        Raises on final failure — callers decide whether to propagate or return empty.
        """
        for attempt in range(3):
            params = {**base_params, **self._get_auth_params()}
            headers = self._get_auth_headers()
            try:
                response = await self.client.get(endpoint, params=params, headers=headers)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401 and self._is_token_mode:
                    self.logger.warning("Token auth failed with 401. Falling back to api-secret mode.")
                    self._is_token_mode = False
                    continue  # Retry immediately with updated auth state; attempt increments
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
            except Exception:
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

        # All attempts exhausted (e.g. a 401 fallback consumed the final attempt).
        # Never fall through to None — callers contract on httpx.Response.
        raise RuntimeError(f"Auth retry exhausted for {endpoint} without a response")

    async def probe_access(self) -> NightscoutAccessResult:
        """Probe the authenticated entries path without exposing provider details."""
        if not self.url or not self.has_credentials:
            return NightscoutAccessResult(
                state="misconfigured", reason="missing_url_or_credential"
            )
        endpoint = f"{self.url}/api/v1/entries.json"
        try:
            await self._request_with_auth_retry(endpoint, {"count": 1})
            return NightscoutAccessResult(state="ok")
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            if status_code in {401, 403}:
                state: AccessState = "rejected"
            elif status_code == 429:
                state = "rate_limited"
            else:
                state = "unreachable"
            return NightscoutAccessResult(
                state=state, reason=f"http_{status_code}"
            )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            return NightscoutAccessResult(
                state="unreachable", reason=error.__class__.__name__
            )
        except Exception as error:
            return NightscoutAccessResult(
                state="unreachable", reason=error.__class__.__name__
            )

    async def fetch_recent_glucose(self, count: int = 20) -> List[GlucoseReading]:
        """Fetches the last N glucose entries from Nightscout with exponential backoff."""
        endpoint = f"{self.url}/api/v1/entries.json"
        response = await self._request_with_auth_retry(endpoint, {"count": count})
        return self._parse_entries(response.json())

    async def fetch_since(self, since_dt: datetime) -> List[GlucoseReading]:
        """
        Fetches all glucose entries since since_dt.
        Uses Nightscout find query syntax.
        """
        endpoint = f"{self.url}/api/v1/entries.json"
        iso_str = since_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        base_params = {"find[dateString][$gt]": iso_str, "count": 1000}
        try:
            response = await self._request_with_auth_retry(endpoint, base_params)
            # Nightscout returns most recent first, we reverse to process chronologically
            readings = self._parse_entries(response.json())
            readings.reverse()
            return readings
        except Exception as e:
            # Task 8.2.1: Non-fatal, live polling will take over.
            self.logger.error(f"Backfill fetch failed after 3 attempts: {e.__class__.__name__}")
            return []

    def _parse_entries(self, entries: List[dict]) -> List[GlucoseReading]:
        """Shared logic for parsing Nightscout entry JSON."""
        readings = []
        for entry in entries:
            if 'sgv' in entry:
                try:
                    mmol_value = normalize_nightscout_sgv(
                        entry["sgv"], entry.get("units")
                    )
                except ValueError as exc:
                    self.logger.warning(
                        "Rejected Nightscout SGV with invalid unit/value: %s", exc
                    )
                    continue

                # Clinical processing is always mmol/L. Display conversion belongs
                # exclusively to presentation adapters.
                value = mmol_value

                # Robust timestamp parsing
                ts_str = entry['dateString'].replace('Z', '+00:00')
                try:
                    # Try isoformat first (standard)
                    ts = datetime.fromisoformat(ts_str)
                except ValueError:
                    # Fallback for non-standard precision or older Python
                    try:
                        ts = datetime.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                    except Exception:
                        continue # Skip unparseable reading
                    
                readings.append(GlucoseReading(
                    timestamp=ts,
                    value=round(value, 2),
                    trend=entry.get('direction', 'Flat'),
                    source="nightscout",
                    source_event_id=(
                        str(entry["_id"]) if entry.get("_id") is not None else None
                    ),
                ))
        return readings

    async def fetch_recent_treatments(self, count: int = 20) -> TreatmentFetchResult:
        """Fetches all insulin and carb events from Nightscout within the 4-hour window."""
        endpoint = f"{self.url}/api/v1/treatments.json"
        try:
            response = await self._request_with_auth_retry(endpoint, {"count": count})
            treatments = response.json()
            now = datetime.now(timezone.utc)

            insulin_list: List[InsulinDose] = []
            meal_list: List[MealEvent] = []

            for t in treatments:
                if 'created_at' not in t:
                    continue

                try:
                    ts = datetime.fromisoformat(t['created_at'].replace('Z', '+00:00'))
                except ValueError:
                    continue

                # C3 Fix: Verify treatment is within 4-hour metabolic window
                if (now - ts).total_seconds() > medical_constants.MEAL_WINDOW_MINS * 60:
                    continue

                # Parse Insulin
                if 'insulin' in t:
                    ev_type = t.get('eventType', 'correction').lower()
                    insulin_type = "RAPID"
                    if any(x in ev_type for x in ["long", "basal", "levermir", "lantus", "tresiba"]):
                        insulin_type = "LONG"

                    insulin_list.append(InsulinDose(
                        timestamp=ts,
                        units=float(t['insulin']),
                        type=insulin_type
                    ))

                # Parse Carbs
                if 'carbs' in t:
                    meal_list.append(MealEvent(
                        timestamp=ts,
                        carbs=float(t['carbs'])
                    ))

            return TreatmentFetchResult(
                source="nightscout",
                state="ok",
                insulin=insulin_list,
                meals=meal_list,
            )

        except Exception as exc:
            self.logger.warning("Treatment fetch degraded: %s", type(exc).__name__)
            return TreatmentFetchResult(
                source="nightscout",
                state="degraded",
                error_reason=type(exc).__name__,
            )

    async def post_treatment(self, event_type: str, notes: str, carbs: Optional[float] = None, insulin: Optional[float] = None):
        """Writes a treatment event back to Nightscout."""
        endpoint = f"{self.url}/api/v1/treatments.json"
        headers = self._get_auth_headers()
        
        now = datetime.now(timezone.utc)
        payload = {
            "enteredBy": "Bio-Quant Metabolic Engine",
            "eventType": event_type,
            "notes": notes,
            "created_at": now.isoformat().replace('+00:00', 'Z'),
            "mills": int(now.timestamp() * 1000),
        }
        if carbs:
            payload["carbs"] = carbs
        if insulin:
            payload["insulin"] = insulin
            
        try:
            response = await self.client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return True
        except Exception as e:
            # Non-fatal
            return False

if __name__ == "__main__":
    import asyncio
    logger = logging.getLogger("Bio-Quant.Test.Nightscout")
    async def test():
        client = NightscoutClient()
        try:
            logger.info("Fetching glucose...")
            data = await client.fetch_recent_glucose(5)
            for d in data: logger.info(f"  {d}")
            logger.info("\nFetching treatments...")
            treatments = await client.fetch_recent_treatments()
            logger.info(
                "  Treatments: %s doses, %s meals (%s)",
                len(treatments.insulin),
                len(treatments.meals),
                treatments.state,
            )
        except Exception as e:
            logger.error(f"Test failed: {e}")
        finally:
            await client.close()
            
    asyncio.run(test())
