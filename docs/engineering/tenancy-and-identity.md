# Tenancy, identity, and scale contract

Updated: 2026-08-12

## Status and boundary

Bio-Quant is a single-patient appliance today. One process owns one Nightscout
connection, Mongo database, Coordinator, snapshot pipeline, twin, oracle, CNN,
model-promotion path, alert destination, and health state. The Vessel Registry can
store multiple Telegram-keyed rows, but that storage shape does not isolate the
clinical runtime.

The selected destination is a shared multi-tenant service. This document defines
that target; it does not make the current runtime multi-tenant. Do not add a second
patient, Nightscout connection, or onboarding flow until the migration and
isolation gates below pass.

## Canonical identity

The sole clinical ownership key is an immutable, server-generated UUID
`patient_id`. It is never derived from a Telegram ID, Nightscout URL, token,
subject, secret, database name, or hash.

Future control-plane records:

- `Patient(id, status, timezone, display_name, created_at)`
- `ExternalIdentity(provider, provider_subject)` with globally unique provider and
  subject
- `PatientAccess(patient_id, identity_id, role, status)` so an identity, such as a
  caregiver, can access more than one patient
- `PatientProfile(patient_id, version, values, state, effective_at)` where state is
  `draft` or `active`
- `NightscoutConnection(patient_id, normalized_url, credential_reference, status,
  last_verified_at)`
- `RuntimeLease(patient_id, owner_id, fencing_token, expires_at)`

Telegram identifies an authenticated principal. An active `PatientAccess` grant
then authorizes that principal for an explicit patient and role. A Nightscout URL
is a connection attribute. Its normalized fingerprint may help detect duplicates,
but never grants access or establishes ownership.

Credentials stay server-side. Connection rows contain a credential reference, not
a raw secret. Ciphertext and the encryption root key must not live in the same
database. Key version, rotation, redaction, and credential access must be audited.
No frontend storage, API response, log, metric label, or audit payload may contain a
raw credential.

## Required ownership invariants

1. Every clinical read, write, event, task, cache key, model artifact, health result,
   alert, audit event, export, backup, and restore operation carries a non-optional
   `patient_id`.
2. Authentication does not select a patient. A multi-patient caregiver must choose
   an active authorized context explicitly; the server never selects a first row or
   stale default.
3. Exactly one runtime owner may produce side effects for a patient. Every commit or
   alert checks a current lease fencing token so a paused old owner cannot act after
   reassignment.
4. Source replay is idempotent by `(patient_id, source, source_event_id)`.
   Timestamps alone are not event identities. Out-of-order events are reordered
   within a bounded window or quarantined for backfill.
5. Suspension or access revocation stops ingestion, commands, alerts, and credential
   use. In-flight work rechecks patient status, authorization, and fencing before a
   side effect.
6. Profile activation is versioned compare-and-swap. One reading is processed using
   one immutable profile version; twin, static vectors, forecasts, and model
   manifests cannot observe a partial update.
7. Alert feedback references both an opaque alert ID and `patient_id`. Telegram
   pending work is keyed by patient, recipient/chat, and message—not message ID
   alone.
8. Service readiness describes shared infrastructure. Patient readiness is scoped
   and authorized separately. Aggregate operator health contains counts, not
   patient identifiers.
9. Restore writes an empty patient-scoped staging namespace after ownership,
   collection, hash, path, schema, and identity checks. Cutover, backup, export,
   retention, and deletion require an explicit patient and idempotent job ID.
10. A normalized Nightscout endpoint cannot have two active patient owners without
    quarantined administrator resolution. Redirects, aliases, or credential
    rotation never change patient identity.

## Target process topology

Python remains the primary language, but process responsibilities must be split:

- Stateless FastAPI control-plane replicas authenticate users, resolve patient
  access, manage profiles/connections, and submit durable commands. They hold no
  authoritative clinical state.
- Runtime shard processes host patient-owned actors. Each `PatientRuntime` owns its
  queue, snapshots, filter, twin, oracle, treatment context, model binding, alert
  state, and health. A lease and fencing token bind it to one shard.
- Bounded CPU worker processes perform profiled inference/forecast work outside the
  runtime event loop. Models load once per worker and are cached by
  `(patient_id, artifact_sha256)`.
- Dedicated training jobs use patient and host quotas. Training never competes with
  alert processing inside API or runtime processes.

Run one stateful runtime process per container and scale with container replicas.
Multiple Uvicorn workers would duplicate in-memory patients, models, locks, and
snapshots rather than share them.

Use `spawn` or `forkserver` explicitly for CPU workers. Worker functions and inputs
must be importable and picklable. Set PyTorch intra-op and inter-op thread counts
from the container CPU budget and benchmark them; do not multiply native thread
pools across workers without limits. A free-threaded CPython build is not an
architecture dependency.

## Data ownership

PostgreSQL is the target control-plane database for patients, access, profiles,
connections, credential references, runtime leases, fencing tokens, command
inbox/outbox, and migrations. Add Alembic before evolving the current schema;
`Base.metadata.create_all()` is only suitable for the current bounded bootstrap.

Raw and staged Nightscout Mongo namespaces remain patient-specific. Normalized
shared collections are permitted only when every record has mandatory
`patient_id`, patient-leading indexes, and repository methods that require an
explicit patient. Application code must not expose unscoped shared collection
handles.

Audit, alerts, and feedback become patient-keyed durable records. Local SQLite may
remain only as a bounded per-process emergency spool with patient and idempotency
metadata, not as the multi-tenant source of truth.

Model object keys, candidates, locks, last-known-good files, and manifests include
`patient_id`, artifact checksum, feature-schema version, profile version, sample
window, and promotion status. A global baseline is marked explicitly. A
patient-trained artifact is never reused for another patient.

## Security and lifecycle edge cases

Connection validation must reject unsupported schemes, embedded credentials,
control characters, and unbounded redirects. Apply SSRF controls: block metadata
and link-local addresses; block private and loopback addresses unless an
administrator enables a local-deployment policy; validate resolved destinations
when connecting to reduce DNS-rebinding risk; and enforce outbound egress policy
where available.

Authorization runs for every request and command execution, not only at session
creation. Revocation invalidates authorization caches. Credential rotation may
briefly reference old and new versions but never copies a secret into a patient
profile.

Patient merge is initially unsupported. Deletion is a fenced workflow: suspend,
resolve export/retention obligations, revoke access and credentials, then purge.
Patient IDs are never reassigned.

Clinical input handling must cover missing, malformed, future, naive, duplicate,
and out-of-order timestamps; unit ambiguity; stale readings; clock skew; provider
partial failure; treatment/glucose split-brain; reconnect storms; and long offline
backfills. One patient's slow provider, corrupt model, alert storm, backfill, or
training job cannot consume another patient's queue, circuit breaker, connection
slots, or CPU budget. Patient-local model failure uses patient-local fallback and
never another patient's artifact or readiness state.

## Migration gates

### A. Control-plane schema

Add Alembic and UUID-based records in PostgreSQL. Backfill exactly one patient for
the current singleton, map the configured patient and optional caregiver Telegram
identities, import traits as an explicit profile version, and attach Nightscout
metadata by credential reference. The migration must be idempotent, resumable,
aggregate-audited, dual-read/compared before cutover, and reversible. A second
patient remains blocked.

Migrate Motor to one PyMongo `AsyncMongoClient` per process/event loop. Do not share
an async client across threads or loops.

### B. Patient runtime actors

Replace `Coordinator._instance` with a runtime manager and patient-owned actors.
Use small per-patient queues and fair scheduling. Latest-wins glucose coalescing is
allowed only after recording a durable gap/backfill marker. Treatments, commands,
profile activation, and alerts are never dropped.

Stagger polling with deterministic jitter, bound provider concurrency, and apply
per-patient retries and circuit breakers. Decouple FastAPI from `COORDINATOR_REF`
through durable projections and an idempotent command inbox/outbox. Prove lease
expiry, fencing, handoff, crash recovery, and split-brain behavior.

### C. Profile and model activation

Save calibration as a draft profile, validate it, and activate it atomically at a
patient actor boundary. Rebuild twin, forecaster, and static inputs from one active
version. Record that version on forecasts and model inputs. Incompatible artifacts
leave only that patient in neural degradation with kinematic fallback.

### D. CPU isolation and overload

Run inference in a bounded process pool or dedicated service. Cache models by
patient and checksum, batch only jobs with compatible deadlines, and correlate
results by patient and job ID. Reserve alert capacity ahead of training and
backfill. Shed optional charting, 24-hour horizons, maintenance, and analytics—in
that order—before safety processing. Every shed path reports a degraded reason.

### E. Onboarding and scale

Only after ownership, authorization, lease, profile, model, restore, and overload
tests pass may administrator-controlled onboarding store a server-side credential
and activate a second patient. Verify a connection in quarantine before ownership
assignment. Duplicate endpoints never activate automatically.

## Capacity gates

Use synthetic or de-identified load at 1, 10, 50, 100, and 500 active patients,
advancing only when the prior tier passes. Exercise steady state, simultaneous
warm-up, provider latency/timeouts, reconnect storms, a noisy patient, process
crash/reassignment, model corruption, profile races, and database degradation.

A tier passes only with:

- zero cross-patient data, results, models, alerts, or health state;
- zero dropped treatments, commands, profile activations, or alert events;
- fresh-reading-to-safety-decision p99 within the chosen operational SLO (initial
  design target: 5 seconds, below the 150-second poll interval);
- API/runtime event-loop lag p99 no greater than 100 ms;
- no patient queue older than one polling interval, with all coalescing measured and
  backfilled;
- sustained CPU no greater than 70% and memory no greater than 80% of container
  limits;
- timely leases and unsaturated database pools/locks;
- patient-isolated model eviction, worker restart, and shard reassignment; and
- graceful durable-work drain plus fencing protection after forced worker loss.

Python should remain practical for tens of active patients after partitioning and
bounded CPU work. Hundreds require several runtime shards, PostgreSQL, scoped Mongo
repositories, leases/fencing, and dedicated CPU/training workers. Thousands require
horizontal shards, managed databases, and possibly a durable broker or model-serving
layer when measurements justify them. Rewrite only a measured bottleneck if Python
scheduling or serialization remains dominant after process and horizontal
isolation, or if a future hard-real-time requirement cannot be met.

## Current calibration truth

The present TWA writes age, weight, and height to a Registry row keyed by the
configured Telegram patient. The active twin, forecaster, and CNN static features
continue to use process configuration. Saving Registry traits therefore does not
change current inference, and restarting alone does not activate those values.
Profile activation belongs to migration gate C.

## References

- CPython threading and GIL: <https://docs.python.org/3/library/threading.html>
- Process-based parallelism: <https://docs.python.org/3/library/multiprocessing.html>
- Async queue backpressure: <https://docs.python.org/3/library/asyncio-queue.html>
- FastAPI worker processes: <https://fastapi.tiangolo.com/deployment/server-workers/>
- SQLite deployment guidance: <https://www.sqlite.org/whentouse.html>
- PyTorch CPU threading: <https://docs.pytorch.org/docs/stable/notes/cpu_threading_torchscript_inference.html>
- PyTorch multiprocessing: <https://docs.pytorch.org/docs/stable/notes/multiprocessing.html>
- PyMongo Async migration: <https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/>
