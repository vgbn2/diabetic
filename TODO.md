# Bio-Quant Project TODO

## 🔴 Critical / Blocker
- [ ] **Fix Nightscout 401 Auth**: Refine `NightscoutClient` token detection logic to handle standard Heroku Secrets that might be incorrectly parsed as tokens.
- [ ] **Process Isolation**: Implement a check in `main.py` to detect if another bot instance is currently active using the same token (via `getMe` or session tracking) to prevent conflicts.

## 🟡 Technical Debt (Phase 1.0 Audit Residuals)
- [ ] **ML Engine Optimization**: Implement reusable tensor buffers in `MetabolicInferenceRunner` to reduce heap churn.
- [ ] **MongoDB Indexing**: Add compound index `(date, eventType)` to optimized `treatments` collection.
- [ ] **Secret Hardening**: Ensure `config.API_SECRET` is zeroed out or removed from the `config` object after `NightscoutClient` initialization.

## 🟢 Feature Backlog
- [ ] **Big JSON Factory**: Implement `data_factory.py` to unify Weather + Air + Bio layers.
- [ ] **FastAPI Migration**: Start Task 2.1 (TWA Backend).
- [ ] **BSON Transformer**: Logic for bulk historical clinical log conversion.

## 🛠️ Infrastructure & Debugging
- [ ] **Auto-Scan on Pause**: Update `/pause` workflow to trigger a mandatory `GSD Codebase Mapper` scan to capture system state.
