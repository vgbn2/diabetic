# Audit: scripts/ (Utilities & Simulations)

## Status: ✅ SOLID

### 📋 Diagnosis
The simulation and utility scripts are fully operational following the Global Patch.
1. **Import Resolution**: All scripts now use `diabetic.*` imports.
2. **Unified Persistence**: Data paths are correctly mapped to `storage/data/processed/`.
3. **Execution Proof**: `climate_sim.py` and `verify_predictive_power.py` run to completion with valid metabolic outputs.

### ✅ Solid Files
- `climate_sim.py`: Climatological 5-day trajectory verified.
- `verify_predictive_power.py`: Statistical audit of engine RMSE functional.
- `visualize_lag.py`: Temporal phase analysis active.

### 🛠️ Required Fix List
- [x] Top-level package transition (`diabetic.*`).
- [x] Redirect CSV paths to `storage/`.
- [x] Redirect chart outputs to `storage/charts/`.
