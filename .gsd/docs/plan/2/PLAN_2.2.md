---
phase: 2
plan: 2
wave: 2
depends_on: ["Plan 2.1"]
files_modified:
  - frontend/src/keep_alive.py
  - frontend/src/db_connector.py
autonomous: true
user_setup:
  - service: Render
    why: "Hosting the Interactive Hub"
    env_vars:
      - name: RENDER_EXTERNAL_URL
---

# Plan 2.2: 24/7 Reliability (Render & MongoDB)

<objective>
Ensure the Frontend Hub remains online 24/7 on Render and maintains a persistent connection to the MongoDB cloud database.

Output: Keep-alive utility and MongoDB handler.
</objective>

<tasks>

<task type="auto">
  <name>Implement Self-Pinging Keep-Alive</name>
  <files>frontend/src/keep_alive.py</files>
  <action>
    Create a lightweight FastAPI/Flask endpoint that pings its own `RENDER_EXTERNAL_URL` every 14 minutes.
    - This prevents Render's free tier from spinning down the instance.
    
    ```python
    import httpx
    import asyncio
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "alive"}

    async def pinger():
        url = os.getenv("RENDER_EXTERNAL_URL") + "/health"
        while True:
            await asyncio.sleep(840) # 14 mins
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(url)
            except Exception:
                pass
    ```
  </name>
  <verify>Check Render logs for periodic /health pings</verify>
  <done>Frontend stays online indefinitely without sleeping</done>
</task>

<task type="auto">
  <name>Implement Persistent MongoDB Connector</name>
  <files>frontend/src/db_connector.py</files>
  <action>
    Implement `MongoManager` using `motor` (async driver).
    - Logic: retry connection on failure with exponential backoff.
    - Used for: Storing interactive user feedback and audit logs.
  </action>
  <verify>python frontend/src/db_connector.py --test-write</verify>
  <done>Database connection is resilient to intermittent network drops</done>
</task>

</tasks>
