---
phase: 17
plan: 1
wave: 1
depends_on: []
files_modified: ["diabetic/utils/db.py", "diabetic/ingestion/mongo.py", "diabetic/utils/audit_logger.py"]
autonomous: true
---

# Plan 17.1: Foundational Database Singleton

<objective>
Eliminate redundant MongoDB connection pools causing Atlas connection exhaustion.
Purpose: Stabilize cloud connectivity and optimize resource usage.
Output: Shared singleton client in `diabetic/utils/db.py`.
</objective>

<context>
- diabetic/ingestion/mongo.py
- diabetic/utils/audit_logger.py
- diabetic/config.py
</context>

<tasks>

<task type="auto">
  <name>Create Database Shared Singleton</name>
  <files>diabetic/utils/db.py</files>
  <action>
    Create a `DatabaseClient` singleton class holding a single `AsyncIOMotorClient`.
    Set `maxPoolSize=10` and `serverSelectionTimeoutMS=5000` as per audit requirement.
    Ensure `close()` method is available for graceful shutdown.
  </action>
  <verify>Import and check singleton ID in two separate modules.</verify>
  <done>Single client instance shared across the app.</done>
</task>

<task type="auto">
  <name>Refactor Ingestion and Audit to use Shared Client</name>
  <files>diabetic/ingestion/mongo.py, diabetic/utils/audit_logger.py</files>
  <action>
    Remove internal `AsyncIOMotorClient` instantiations.
    Inject the shared singleton from `diabetic.utils.db`.
  </action>
  <verify>Run `git grep "AsyncIOMotorClient"` to ensure only one instantiation remains.</verify>
  <done>Redundant pools removed.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Only one MongoDB connection active in Atlas logs (or local simulation).
- [ ] Audit logs and Ingestion both function without connection errors.
</verification>
