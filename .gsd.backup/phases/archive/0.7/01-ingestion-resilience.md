---
phase: 0.7
plan: 1
wave: 1
depends_on: []
files_modified: ["diabetic/ingestion/nightscout.py", "diabetic/ingestion/mongo.py"]
autonomous: true
must_haves:
  truths:
    - "Nightscout live polling succeeds without 401 Unauthorized errors"
    - "MongoDB retention cleanup executes against the correct database object without silently bypassing"
  artifacts: []
---

# Plan 0.7.1: Ingestion Resilience & Nightscout Auth

<objective>
Resolve critical ingestion blockers identified in the v18 Audit, specifically the Nightscout 401 Unauthorized API blocker and the MongoDB retention script's silent guard failure (C1).

Purpose: Enable live polling to resume without crashes and ensure automated cleanup keeps the database lean.
Output: Hardened ingestion layer scripts.
</objective>

<context>
Load for context:
- diabetic/ingestion/nightscout.py
- diabetic/ingestion/mongo.py
</context>

<tasks>

<task type="auto">
  <name>Nightscout API Auth Modernization</name>
  <files>diabetic/ingestion/nightscout.py</files>
  <action>
    Refactor `_get_headers` to return headers, and implement logic in `fetch_recent_glucose` and `fetch_recent_treatments` to pass the `token` query parameter if the `API_SECRET` resembles an access token (rather than just using the `api-secret` or `Authorization` headers). 
    AVOID: Breaking existing SHA1 hash compatibility for older Nightscout instances, ensure both are attempted or gracefully parsed.
  </action>
  <verify>python scratch/test_ns_auth.py (or equivalent script) returns 200 OK</verify>
  <done>Nightscout live polling completes successfully</done>
</task>

<task type="auto">
  <name>Fix C1: MongoDB Retention Null DB Crash</name>
  <files>diabetic/ingestion/mongo.py</files>
  <action>
    Update `MongoDBClient.run_retention_cleanup`. Change the guard `if self.db is None: return` to `if self.entries is None: return` (or `self.db_manager.entries`).
    Ensure the actual deletion logic inside the try-block correctly references the active `entries` and `treatments` collections instead of a non-existent `self.db`.
    AVOID: Removing the 180-day retention constraint.
  </action>
  <verify>grep "self.db is None" diabetic/ingestion/mongo.py should return nothing</verify>
  <done>run_retention_cleanup references the correct collections and guards safely</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Nightscout can be polled live
- [ ] MongoDB retention guard is fixed
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
