# Research: Phase 1.1 Multi-Tenant SQL Registry

## Objectives
- Determine the best SQL Alchemy configuration for Heroku (Postgres) and Local (SQLite).
- Define the schema for `VesselRegistry`.
- Outline the migration strategy from `.env` to DB.

## Findings

### 1. Database Connection
- **Local**: Use `sqlite:///./diabetic/storage/vessel_registry.db`.
- **Production (Heroku)**: Use `DATABASE_URL` from environment.
- **Heroku Fix**: Heroku provides `postgres://` URLs, but SQLAlchemy 1.4+ requires `postgresql://`.
  - *Code snippet*: `db_url = os.environ.get('DATABASE_URL').replace('postgres://', 'postgresql://', 1)`
- **SSL**: Heroku Postgres requires `?sslmode=require` or specific engine parameters if the URL is old.

### 2. Schema Design (VesselRegistry)
Based on `ROADMAP.md`:
- `User` table: `telegram_id` (BigInt, PK), `name`, `created_at`.
- `BioTraits` table: linked to `User`, contains clinical data (Age, Height, etc.).
- `CulturalMarkers` table: linked to `User` (Nationality, Religion).
- `MedicalStates` table: linked to `User` (SickMode, DawnPhenomenon).

### 3. Migration Strategy
1. **Bootstrap**: Create tables if they don't exist (using `Base.metadata.create_all`).
2. **Seed**: If a user is currently defined in `.env` (legacy mode), migrate their data into the DB on first run if their `telegram_id` matches.

## Decisions
- Use **SQLAlchemy** (async mode if possible, but standard sync is safer for now if we want to avoid complex async DB sessions).
- Actually, `requirements.txt` has `motor` (async). We should probably use `databases` or `asyncpg` if we want full async, but standard SQLAlchemy 2.0 with `aiosqlite` / `asyncpg` is the modern way.
- **Constraint**: The orchestrator is already async. We MUST use an async-compatible DB layer to prevent blocking the main loop.

## Next Steps
- Implement `diabetic/storage/vessel_registry.py` with SQLAlchemy async engine.
- Define models in `diabetic/storage/models.py`.
