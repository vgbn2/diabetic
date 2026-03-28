# Charts Visualize (Deferred Module)

This folder contains the visualization logic for the **Hyperglycemia Faint Predictor**. It has been decoupled from the core `diabetic/` directory to keep the local execution engine lean and focused on metabolic intelligence.

## 📁 Contents
- `visualizer.py`: Core `matplotlib` charting logic for 4-hour glucose forecasts.

## 🔮 Future Integration
When the system is migrated to a **Persistent Server** or a cloud environment, this module should be reintegrated into the `Coordinator` pipeline.

### Steps to Re-enable:
1.  Move `visualizer.py` back to `diabetic/ui/`.
2.  Uncomment the visualizer imports and initialization in `diabetic/coordinator.py`.
3.  Ensure the `charts/` directory is writable for PNG generation.
4.  Re-enable `await self.notifier.send_chart(...)` in `handle_meal_input`.

## 🧪 Current Status
- **Functional**: The code is tested and works in standalone mode.
- **Decision**: Deferred to prioritize core "Adaptive Twin" and "Regime Detection" logic.
