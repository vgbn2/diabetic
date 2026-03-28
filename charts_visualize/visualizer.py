import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from typing import List, Optional
import os

class MetabolicVisualizer:
    """
    Renders 4-hour metabolic forecasts as high-fidelity charts.
    """
    def __init__(self, output_dir: str = "charts"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def plot_forecast(self, history: List[float], prediction: np.ndarray, meal_name: str = "Meal") -> str:
        """
        Generates a 4-hour forecast chart.
        Args:
            history: List of last 12 readings (60 mins).
            prediction: Array of 48 predicted points (4 hours).
        Returns:
            Path to the saved image.
        """
        plt.figure(figsize=(10, 6))
        plt.style.use('dark_background')
        
        # X-axis setup (minutes relative to 'now')
        history_t = np.arange(-60, 0, 5)[:len(history)]
        predict_t = np.arange(0, 245, 5)
        
        # Plot History
        plt.plot(history_t, history, color='cyan', linewidth=2, label='Actual (Last 60m)')
        plt.scatter(history_t, history, color='cyan', s=30)
        
        # Plot Prediction
        plt.plot(predict_t, prediction, color='red', linestyle='--', linewidth=2, label=f'Digital Twin ({meal_name})')
        plt.fill_between(predict_t, prediction - 0.5, prediction + 0.5, color='red', alpha=0.1)
        
        # Thresholds
        plt.axhline(y=16.7, color='yellow', linestyle=':', label='Faint Risk (300 mg/dL)')
        plt.axhline(y=3.9, color='red', linestyle=':', label='Hypo Warning')
        
        # Labels
        plt.title(f"Metabolic Forecast: {meal_name}", fontsize=14, color='white')
        plt.xlabel("Minutes from Now", fontsize=10)
        plt.ylabel("Glucose (mmol/L)", fontsize=10)
        plt.legend(loc='upper left')
        plt.grid(True, alpha=0.2)
        
        # Save
        filename = f"forecast_{datetime.now().strftime('%H%M%S')}.png"
        path = os.path.join(self.output_dir, filename)
        plt.savefig(path)
        plt.close()
        
        return os.path.abspath(path)

if __name__ == "__main__":
    # Test Visualizer
    viz = MetabolicVisualizer()
    hist = [8.0, 8.2, 8.5, 8.7, 9.0, 9.2, 9.5, 9.7, 10.0, 10.2, 10.5, 10.7]
    pred = np.linspace(10.7, 15.0, 49) # Dummy prediction
    path = viz.plot_forecast(hist, pred, "Test Meal")
    print(f"Chart saved to: {path}")
