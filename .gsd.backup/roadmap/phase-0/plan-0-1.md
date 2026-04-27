---
phase: 0
plan: 1
wave: 1
depends_on: []
files_modified:
  - diabetic/ingestion/weather.py
  - diabetic/utils/stateless_push.py
  - diabetic/ingestion/nightscout.py
autonomous: true
---

# Plan 0.1: Ingestion & Telemetry Hardening

<objective>
Refactor high-frequency ingestors to use persistent HTTP clients and implement explicit lifecycle management to prevent socket leaks.

Purpose: Prevent connection exhaustion in production environments.
Output: Refactored weather, push, and discovery components.
</objective>

<context>
Load for context:
- .gsd/STATE.md
- diabetic/ingestion/weather.py
- diabetic/utils/stateless_push.py
- diabetic/ingestion/nightscout.py
</context>

<tasks>

<task type="auto">
  <name>Refactor WeatherIngestor (HTTPX + Persistent)</name>
  <files>diabetic/ingestion/weather.py</files>
  <action>
    - Replace `aiohttp` with `httpx`.
    - Initialize `self.client = httpx.AsyncClient()` in `__init__`.
    - Log `WARNING` in `__init__` if `self.mock_mode` is True.
    - Update `fetch_current` to use `self.client`.
    - Implement `async def close(self)` to `await self.client.aclose()`.
  </action>
  <verify>Run `python diabetic/ingestion/weather.py` (if testable) or confirm no syntax errors.</verify>
  <done>WeatherIngestor uses a persistent httpx client and has a close method.</done>
</task>

<task type="auto">
  <name>Harden StatelessPush Persistence</name>
  <files>diabetic/utils/stateless_push.py</files>
  <action>
    - Initialize `self.client = httpx.AsyncClient()` in `__init__`.
    - Refactor `push_update` and `heartbeat` to use `self.client` instead of local `async with` contexts.
    - Implement `async def close(self)` to `await self.client.aclose()`.
  </action>
  <verify>Static analysis for async context removal.</verify>
  <done>StatelessPush reuses a single client and manages its lifecycle.</done>
</task>

<task type="auto">
  <name>Add Lifecycle to NightscoutClient</name>
  <files>diabetic/ingestion/nightscout.py</files>
  <action>
    - Implement `async def close(self)` to `await self.client.aclose()`.
    - This ensures the existing persistent client is gracefully shutdown.
  </action>
  <verify>Presence of close() method.</verify>
  <done>NightscoutClient has an explicit shutdown hook.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] No occurrences of `aiohttp` in `weather.py`.
- [ ] `WeatherIngestor` logs a warning when mocking.
- [ ] All three files have a `close()` method targeting their internal client.
</verification>

<success_criteria>
- [ ] Ingestor connection leaks are mathematically impossible (sessions are persistent).
- [ ] Lifecycle hooks are ready for Coordinator integration.
</success_criteria>
