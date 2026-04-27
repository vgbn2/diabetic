---
phase: 0
plan: 2
wave: 2
depends_on: ["plan-0.1"]
files_modified:
  - diabetic/utils/db.py
  - diabetic/coordinator.py
autonomous: true
---

# Plan 0.2: Orchestration & Infrastructure Hardening

<objective>
Integrate ingestor lifecycle hooks into the main Coordinator loop and remediate background task crashes in the semantic memory layer.

Purpose: Achieve 100% graceful shutdown and background task stability.
Output: Hardened coordinator and database management.
</objective>

<context>
Load for context:
- .gsd/STATE.md
- diabetic/utils/db.py
- diabetic/coordinator.py
</context>

<tasks>

<task type="auto">
  <name>Add Database Lifecycle Hook</name>
  <files>diabetic/utils/db.py</files>
  <action>
    - Implement `async def close(self)` in `DatabaseSingleton`.
    - Content: `if self.client: self.client.close()`.
  </action>
  <verify>Presence of close() method in db.py.</verify>
  <done>DatabaseSingleton can be explicitly closed.</done>
</task>

<task type="auto">
  <name>Patch Coordinator for Stability & Shutdown</name>
  <files>diabetic/coordinator.py</files>
  <action>
    - **Null-Check**: In `_process_reading`, add `if self.palace is not None:` before the `asyncio.to_thread(self.palace.remember_snapshot, ...)` call (Line 222).
    - **Shutdown Orchestration**: In `stop()`, add:
        - `await self.client.close()`
        - `await self.weather_client.close()`
        - `await self.pusher.close()`
        - `if self.mongo: await self.mongo.db_manager.close()`
  </action>
  <verify>Code review of stop() method and reading loop.</verify>
  <done>Coordinator closes all clients and handles missing Palace without crashing background tasks.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] `Coordinator.stop()` is awaited in any test/live scripts and correctly shuts down all 4 major clients.
- [ ] No `AttributeError` when `metabolic_palace` fails to import.
</verification>

<success_criteria>
- [ ] Audit finding 6 (Palace NoneType) is resolved.
- [ ] Audit finding 2 (Shutdown leaks) is resolved.
- [ ] Database connection pool is reclaimed on stop.
</success_criteria>
