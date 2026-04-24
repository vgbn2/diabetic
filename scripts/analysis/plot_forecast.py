import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
import shutil

# Read the data
csv_path = 'data/forecasts/2026-04-24_5day_forecast.csv'
df = pd.read_csv(csv_path)

# Convert timestamp
df['timestamp'] = pd.to_datetime(df['timestamp_utc'])

# Plot
plt.figure(figsize=(15, 7))

plt.plot(df['timestamp'], df['glucose_mmol_l'], label='Mechanistic + Neural Glucose (mmol/L)', color='#1f77b4', linewidth=1.5)

# Add thresholds
plt.axhline(y=3.9, color='red', linestyle='--', alpha=0.5, label='Hypo (3.9)')
plt.axhline(y=14.0, color='orange', linestyle='--', alpha=0.5, label='Hyper (14.0)')
plt.axhline(y=11.5, color='gray', linestyle=':', alpha=0.5, label='Renal Clear (11.5)')

# Formatting
plt.title('5-Day Metabolic Forecast (Circadian + Imbalance Modeled)', fontsize=14)
plt.ylabel('Glucose (mmol/L)', fontsize=12)
plt.xlabel('Time', fontsize=12)
plt.ylim(2.0, 18.0) # Set rigid clinical boundaries for clear visualization
plt.grid(True, alpha=0.3)
plt.legend(loc='upper right')

# X-axis formatting
ax = plt.gca()
ax.xaxis.set_major_locator(mdates.DayLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=range(0, 24, 6)))
plt.xticks(rotation=45)

plt.tight_layout()

# Save
local_img_path = 'data/forecasts/forecast_plot.png'
plt.savefig(local_img_path, dpi=150)
print(f"Saved plot to {local_img_path}")

# Copy to artifacts directory
artifact_dir = r"C:\Users\Lenovo\.gemini\antigravity\brain\831e32d2-df04-499c-97e4-478c48be0d3c"
artifact_img_path = os.path.join(artifact_dir, "forecast_plot.png")
shutil.copy(local_img_path, artifact_img_path)
print(f"Copied plot to {artifact_img_path}")
