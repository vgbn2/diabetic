---
phase: 1.1
plan: 1
wave: 1
---

# Plan 1.1.1: Multi-Tenant SQL Foundation

## Objective
Establish the SQLAlchemy-based storage layer for the Vessel Registry, supporting both Local (SQLite) and Production (Heroku Postgres) environments with a multi-tenant schema.

## Context
- .gsd/SPEC.md
- .gsd/ROADMAP.md
- .gsd/phases/1.1/RESEARCH.md
- diabetic/config.py (legacy settings)

## Tasks

<task type="auto">
  <name>Implement Registry Infrastructure</name>
  <files>
    - diabetic/storage/engine.py [NEW]
    - diabetic/storage/models.py [NEW]
  </files>
  <action>
    Create a robust, async-capable database engine factory that:
    1. Detects `DATABASE_URL` for Heroku (fixing 'postgres://' to 'postgresql://').
    2. Falls back to SQLite at `diabetic/storage/vessel_registry.db` for local dev.
    3. Defines the SQLAlchemy ORM models for Users, BioTraits, and CulturalMarkers as specified in RESEARCH.md.
    4. Includes a `init_db()` function to create tables on startup.
  </action>
  <verify>python -c "import asyncio; from diabetic.storage.engine import init_db; asyncio.run(init_db())"</verify>
  <done>Database file created locally and models verified with SQLAlchemy reflection.</done>
</task>

<task type="auto">
  <name>Migrate ENV to Registry Logic</name>
  <files>
    - diabetic/storage/registry_v2.py [NEW]
    - diabetic/config.py [MODIFY]
  </files>
  <action>
    1. Create `registry_v2.py` as a service layer to interact with the SQL models.
    2. Implement a 'Legacy Migration' check: if `.env` contains specific bio-traits (Age, Weight), upsert them into the database for the primary user.
    3. Update `config.py` to optionally load settings from the `registry_v2` service if a user_id is provided.
  </action>
  <verify>python -m diabetic.storage.registry_v2 --migrate</verify>
  <done>Environment variables successfully mirrored in the local SQLite database.</done>
</task>

## Success Criteria
- [ ] SQLAlchemy engine handles Heroku Postgres URLs correctly.
- [ ] User bio-traits are successfully persisted in SQL tables.
- [ ] System boots locally using SQLite without manual DB setup.
