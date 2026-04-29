import asyncio
import logging
import matplotlib
matplotlib.use('Agg') # Headless support (Task 8.3.1)
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timezone
from typing import List, Optional
import os
import io
from diabetic.config import config
from diabetic.medical_constants import (
    SAMPLING_INTERVAL_MINS, 
    FAINT_GLUCOSE, 
    HYPO_WARNING,
    RENAL_THRESHOLD,
    LOW_SIDE_THRESHOLD
)
from diabetic.registry import MetabolicSnapshot

logger = logging.getLogger("Bio-Quant.UI.Visualizer")

class MetabolicVisualizer:
    """
    Renders 4-hour metabolic forecasts and live session dashboards.
    Enhanced with 3D Kinematics and Cyberpunk-Dark aesthetics.
    """
    def __init__(self, output_dir: str = "charts"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        
        # Apply Cyberpunk-Dark styling
        plt.style.use('dark_background')
        self.colors = {
            'glucose': '#00f2ff',      # Neon Cyan
            'prediction': '#ff0055',   # Neon Pink
            'velocity': '#00ff41',     # Matrix Green
            'acceleration': '#ffaa00', # Neon Orange
            'heart_rate': '#ff4d4d',   # Soft Red
            'grid': '#1a1a1a',
            'zone_safe': '#00ff411a',  # Translucent Green
            'zone_warn': '#ffaa001a',  # Translucent Orange
        }

    def _save_continuous_sync(self, snapshots: List[MetabolicSnapshot]):
        """
        Thread-safe render (Fix H3).
        Uses Object-Oriented matplotlib API to avoid global state corruption.
        """
        if not snapshots:
            return

        # Prepare Data (Wave 5/6: Dynamic Windowing)
        window_size = int(config.LIVE_HISTORY_HOURS * (60 / SAMPLING_INTERVAL_MINS))
        window = snapshots[-window_size:]
        
        # Relative time in minutes from present
        times = [(s.glucose.timestamp - snapshots[-1].glucose.timestamp).total_seconds() / 60 for s in window]
        glucose = [s.glucose.value for s in window]
        velocity = [s.velocity if s.velocity else 0.0 for s in window]
        bpm = [s.bpm if s.bpm else 0.0 for s in window]

        from matplotlib.figure import Figure
        fig = Figure(figsize=(12, 10))
        fig.patch.set_facecolor('#0a0a0a')
        ax_g, ax_k = fig.subplots(2, 1, gridspec_kw={'height_ratios': [2, 1]})

        # --- SUBPLOT 1: GLUCOSE ---
        ax_g.set_facecolor('#0f0f0f')
        ax_g.plot(times, glucose, color=self.colors['glucose'], linewidth=2.5, label='Glucose (mmol/L)')
        ax_g.scatter(times[-1], glucose[-1], color=self.colors['glucose'], s=100, zorder=5)
        
        # Thresholds
        ax_g.axhline(y=FAINT_GLUCOSE, color='#ff0000', linestyle='--', alpha=0.5, label='Faint Risk')
        ax_g.axhline(y=HYPO_WARNING, color='#ffaa00', linestyle=':', alpha=0.5, label='Hypo Warning')
        
        # Shaded Time-in-Range
        ax_g.fill_between(times, LOW_SIDE_THRESHOLD, RENAL_THRESHOLD, color=self.colors['zone_safe'], alpha=0.1)
        
        ax_g.set_title(" LIVE METABOLIC DASHBOARD ", fontsize=16, fontweight='bold', color='white', pad=20)
        ax_g.set_ylabel("Glucose", fontsize=12, color='white')
        ax_g.grid(True, which='both', color=self.colors['grid'], alpha=0.3)
        ax_g.legend(loc='upper left', frameon=False)

        # --- SUBPLOT 2: KINEMATICS ---
        ax_k.set_facecolor('#0f0f0f')
        ax_k.plot(times, velocity, color=self.colors['velocity'], linewidth=1.5, label='Velocity (mmol/L/min)')

        if any(bpm):
            ax_hr = ax_k.twinx()
            ax_hr.plot(times, bpm, color=self.colors['heart_rate'], linewidth=1.0, linestyle='--', alpha=0.7, label='BPM')
            ax_hr.set_ylabel("Heart Rate", color=self.colors['heart_rate'])
            ax_hr.tick_params(axis='y', labelcolor=self.colors['heart_rate'])

        ax_k.set_xlabel("Minutes from Present", fontsize=10, color='white')
        ax_k.set_ylabel("Metabolic Force", fontsize=10, color='white')
        ax_k.grid(True, color=self.colors['grid'], alpha=0.3)
        ax_k.legend(loc='upper left', frameon=False)

        fig.tight_layout()
        save_path = os.path.join(self.output_dir, "live_dashboard.png")
        fig.savefig(save_path, facecolor=fig.get_facecolor(), dpi=120)

    def update_continuous(self, snapshots: List[MetabolicSnapshot]):
        """Non-blocking dashboard update — dispatches savefig to a thread."""
        if not snapshots:
            return
        
        # Deep copy list to avoid mutation during thread rendering
        snap_copy = list(snapshots)
        
        try:
            loop = asyncio.get_running_loop()  # Fix H5: get_running_loop raises RuntimeError outside loop
            # Task 8.3.1: Run in executor to prevent blocking the async polling loop
            loop.run_in_executor(None, self._save_continuous_sync, snap_copy)
        except RuntimeError:
            self._save_continuous_sync(snap_copy)

    def plot_forecast(self, history: List[float], prediction: np.ndarray, meal_name: str = "Meal") -> str:
        """
        Generates a 4-hour forecast chart as a PNG file.
        Returns the absolute path.
        """
        buf = self.render_forecast_buffer(history, prediction, meal_name)
        filename = f"forecast_{datetime.now().strftime('%H%M%S')}.png"
        path = os.path.join(self.output_dir, filename)
        
        with open(path, 'wb') as f:
            f.write(buf.getbuffer())
            
        return os.path.abspath(path)

    def render_forecast_buffer(self, history: List[float], prediction: np.ndarray, meal_name: str = "Meal") -> io.BytesIO:
        """
        Thread-safe render (Fix H3).
        Uses Sampling-Agnostic temporal scaling (Wave 6).
        """
        from matplotlib.figure import Figure
        fig = Figure(figsize=(10, 6))
        ax = fig.add_subplot(111)
        ax.set_facecolor('#0f0f0f')
        fig.patch.set_facecolor('#0a0a0a')
        
        # Hardening: Use SAMPLING_INTERVAL_MINS instead of hardcoded 5
        history_t = np.arange(-SAMPLING_INTERVAL_MINS * len(history), 0, SAMPLING_INTERVAL_MINS)
        predict_t = np.arange(0, SAMPLING_INTERVAL_MINS * len(prediction), SAMPLING_INTERVAL_MINS)
        
        # Plot History
        ax.plot(history_t, history, color=self.colors['glucose'], linewidth=2.5, label='Actual (Historical)')
        ax.scatter(history_t[-1], history[-1], color=self.colors['glucose'], s=50)
        
        # Plot Prediction
        ax.plot(predict_t, prediction, color=self.colors['prediction'], linestyle='--', linewidth=2, label=f'Digital Twin ({meal_name})')
        ax.fill_between(predict_t, prediction - 0.5, prediction + 0.5, color=self.colors['prediction'], alpha=0.1)
        
        # Annotate Peak
        peak_idx = np.argmax(prediction)
        peak_val = prediction[peak_idx]
        peak_time = predict_t[peak_idx]
        ax.annotate(f"Peak: {peak_val:.1f}", xy=(peak_time, peak_val), xytext=(peak_time+10, peak_val+1),
                     arrowprops=dict(facecolor='white', shrink=0.05, width=1, headwidth=5),
                     color='white', fontweight='bold')
        
        ax.axhline(y=FAINT_GLUCOSE, color='red', linestyle='--', alpha=0.3)
        
        ax.set_title(f"DIGITAL TWIN FORECAST: {meal_name.upper()}", fontsize=14, fontweight='bold', color='white')
        ax.set_xlabel("Minutes from Now", color='silver')
        ax.set_ylabel("Glucose (mmol/L)", color='silver')
        ax.legend(frameon=False)
        ax.grid(True, color=self.colors['grid'], alpha=0.3)
        
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120)
        buf.seek(0)
        return buf

if __name__ == "__main__":
    # Test Visualizer
    viz = MetabolicVisualizer("test_charts")
    hist = [8.0, 8.2, 8.5, 8.7, 9.0, 9.2, 9.5, 9.7, 10.0, 10.2, 10.5, 10.7]
    pred = np.linspace(10.7, 15.0, 49) 
    viz.plot_forecast(hist, pred, "Test Meal")
    logger.info("Test chart generated.")
