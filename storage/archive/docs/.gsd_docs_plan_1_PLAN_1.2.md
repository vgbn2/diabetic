---
phase: 1
plan: 2
wave: 1
depends_on: ["Plan 1.1"]
files_modified:
  - src/ingestion/nightscout_client.py
  - src/ingestion/sim_reader.py
autonomous: true
user_setup:
  - service: Nightscout
    why: "Primary data source"
    env_vars:
      - name: NIGHTSCOUT_URL
      - name: API_SECRET
must_haves:
  truths:
    - "System can pull real-time glucose from Nightscout API"
    - "System can replay JSON/CSV files for offline development (Simulation)"
  artifacts:
    - "src/ingestion/nightscout_client.py exists"
---

# Plan 1.2: Nightscout Bridge & Sim Reader

<objective>
Enable data flow into the system from both live medical APIs and historical simulation files.

Output: Resilient ingestion clients.
</objective>

<context>
Load for context:
- .gsd/docs/SPEC.md
- src/registry.py
- src/config.py
</context>

<tasks>

<task type="auto">
  <name>Build Nightscout Client</name>
  <files>src/ingestion/nightscout_client.py</files>
  <action>
    Implement an async `NightscoutClient` using `httpx`.
    - Function: `get_latest_glucose()` returns `GlucoseReading`.
    - Security: Use SHA1 hash of API_SECRET for authentication.

    ```python
    import httpx
    import hashlib
    from src.registry import GlucoseReading

    class NightscoutClient:
        def __init__(self, url, secret):
            self.url = url
            self.hashed_secret = hashlib.sha1(secret.encode()).hexdigest()
            
        async def fetch_recent(self) -> list[GlucoseReading]:
            async with httpx.AsyncClient() as client:
                res = await client.get(f"{self.url}/api/v1/entries.json", headers={"api-secret": self.hashed_secret})
                return [GlucoseReading(**item) for item in res.json()]
    ```
  </action>
  <verify>python src/ingestion/nightscout_client.py (mocked)</verify>
  <done>Nightscout data can be ingested and cast to internal types</done>
</task>

<task type="auto">
  <name>Implement Simulation Reader</name>
  <files>src/ingestion/sim_reader.py</files>
  <action>
    Implement a generator that reads rows from a local CSV/JSON and yields `GlucoseReading` objects on a timer (to simulate real-time).
  </action>
  <verify>python src/ingestion/sim_reader.py --file data/sample.csv</verify>
  <done>Developer can test the entire pipeline without a live internet connection</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] API client handles 401 Unauthorized gracefully.
- [ ] Sim reader correctly parses historical timestamps.
</verification>

<success_criteria>
- [ ] Bidirectional ingestion paths (Live/Sim) are functional.
</success_criteria>
