---
name: Bio-Quant Protocols
description: Strict engineering and medical rules for developing the Bio-Quant Metabolic Intelligence Engine.
---

# Bio-Quant Engineering Protocols

This skill outlines the strict engineering and clinical rules required for any development work on the Bio-Quant project. You MUST adhere to these guidelines at all times to ensure clinical safety, backend scalability, and machine learning determinism.

## 1. Security & Process Isolation
- **Singleton Processes:** You MUST ensure background jobs and entrypoints implement a strict `.bot.lock` PID-based lock mechanism to prevent "Split-Brain" execution loops.
- **Secret Handling:** You MUST NOT store raw `.env` secrets (like API keys or tokens) as persistent instance attributes. Hash them immediately or convert them to short-lived headers and allow the raw text to drop out of memory.
- **Fail-Fast Auth:** You MUST implement graceful degradation for 401 Unauthorized API responses using `try/except` fallbacks before initiating exponential backoff.

## 2. Scalability & Networking
- **Connection Pooling:** You MUST use persistent `httpx.AsyncClient` objects initialized at the class level for any repeating network I/O. Do NOT spawn a new client per request.
- **Graceful Shutdown:** You MUST provide and execute an `async def close(self)` method to properly shut down any `httpx` or database client connections.
- **Containerization:** All system components MUST be designed to run orchestrated via `docker-compose`, using pure environment variable injection without hardcoded configurations.

## 3. Maintainability & ML Determinism
- **Global Seeding:** You MUST explicitly seed all machine learning components at the top of the file:
  ```python
  torch.manual_seed(42)
  np.random.seed(42)
  random.seed(42)
  if torch.cuda.is_available():
      torch.cuda.manual_seed_all(42)
  ```
- **Clinical Accuracy:** All medical constants MUST include mathematically precise inline comments converting between mmol/L and mg/dL (Factor: 18.018).
  - e.g., `HYPER_CRITICAL = 16.0  # ~288 mg/dL`
- **Asynchronous Boundaries:** Neural inference and Kalman filtering MUST be decoupled from data ingestion via `asyncio.Queue` structures.

## 4. GSD Workflow Adherence
- All changes MUST be grouped logically into tasks and verified empirically before completion.
- When you execute a plan, you MUST follow the verification steps precisely. "Trust me, it works" is UNACCEPTABLE in this repository.
