import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import argparse
from pathlib import Path
from datetime import datetime
import numpy as np
from matplotlib.gridspec import GridSpec

def plot_forecast(csv_path: str, output_path: str = None):
    """
    Plots a multi-layer metabolic forecast with schedule-aware context.
    Panel 1: Glucose + Event Markers
    Panel 2: Cardiac (BPM/HRV) + Shading
    """
    print(f"Generating Premium Forecast Visualization: {csv_path}")
    
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp_utc'])
    df = df.sort_values('timestamp')

    # Split into 24-hour panels for readability
    days = df['timestamp'].dt.date.unique()
    num_days = len(days)
    
    # Match styling of plot_glucose.py
    plt.style.use('seaborn-v0_8-whitegrid')
    fig = plt.figure(figsize=(24, 10 * num_days), constrained_layout=True)
    gs = GridSpec(num_days, 1, figure=fig)

    for i, day in enumerate(days):
        day_gs = gs[i].subgridspec(2, 1, height_ratios=[2, 1], hspace=0.1)
        ax_g = fig.add_subplot(day_gs[0])
        ax_c = fig.add_subplot(day_gs[1], sharex=ax_g)
        
        day_df = df[df['timestamp'].dt.date == day]
        if day_df.empty: continue

        # --- PANEL 1: GLUCOSE ---
        ax_g.plot(day_df['timestamp'], day_df['glucose_mmol_l'], color='#0984e3', linewidth=2.5, alpha=0.9, zorder=5, label='Glucose (Predicted)')
        ax_g.scatter(day_df['timestamp'], day_df['glucose_mmol_l'], color='#0984e3', s=10, alpha=0.12, edgecolors='none', zorder=6)
        
        ax_g.axhspan(3.9, 10.0, color='#00b894', alpha=0.12, label='Target Range')
        ax_g.axhline(10.0, color='#d63031', linestyle=':', alpha=0.5, linewidth=1.5)
        ax_g.axhline(3.9,  color='#e17055', linestyle=':', alpha=0.5, linewidth=1.5)
        
        # Annotate Max/Min (Same style as plot_glucose.py)
        idxmax = day_df['glucose_mmol_l'].idxmax()
        idxmin = day_df['glucose_mmol_l'].idxmin()
        
        ax_g.annotate(
            f"{day_df.loc[idxmax, 'glucose_mmol_l']:.1f}",
            xy=(mdates.date2num(day_df.loc[idxmax, 'timestamp']), day_df.loc[idxmax, 'glucose_mmol_l']),
            xytext=(0, 10), textcoords='offset points',
            ha='center', va='bottom', fontsize=10, fontweight='bold', color='white',
            bbox=dict(boxstyle="round,pad=0.3", fc="#d63031", ec="none", alpha=0.9), zorder=10
        )
        ax_g.annotate(
            f"{day_df.loc[idxmin, 'glucose_mmol_l']:.1f}",
            xy=(mdates.date2num(day_df.loc[idxmin, 'timestamp']), day_df.loc[idxmin, 'glucose_mmol_l']),
            xytext=(0, -10), textcoords='offset points',
            ha='center', va='top', fontsize=10, fontweight='bold', color='white',
            bbox=dict(boxstyle="round,pad=0.3", fc="#e17055", ec="none", alpha=0.9), zorder=10
        )

        # Meal/Bolus Markers (Matching plot_glucose.py marker style)
        meals = day_df[day_df['meal_carbs'] > 0]
        if not meals.empty:
            ax_g.scatter(meals['timestamp'], [day_df['glucose_mmol_l'].max() + 1.2] * len(meals), 
                        marker='^', color='#fdcb6e', s=120, label='Meal Events', zorder=11)
            
        # Stress Markers
        stress = day_df[(day_df['meal_carbs'] > 0) & (day_df['event_type'] == 'ROUTINE')]
        if not stress.empty:
             ax_g.scatter(stress['timestamp'], [day_df['glucose_mmol_l'].max() + 2.2] * len(stress), 
                         marker='*', color='#d63031', s=150, label='Unexpected Stress', zorder=11)

        ax_g.set_ylabel("Glucose (mmol/L)", fontsize=13)
        ax_g.set_title(f"Metabolic Forecast: {day.strftime('%A, %b %d')}", fontsize=16, fontweight='bold', pad=15, color='#2d3436')
        ax_g.set_ylim(0, max(day_df['glucose_mmol_l'].max() + 4, 16))

        # --- PANEL 2: CARDIAC ---
        ax_c.plot(day_df['timestamp'], day_df['heart_rate_bpm'], color='#e17055', linewidth=2, alpha=0.8, label='BPM')
        ax_c.fill_between(day_df['timestamp'], day_df['heart_rate_bpm'], color='#e17055', alpha=0.1)
        
        ax_hrv = ax_c.twinx()
        ax_hrv.plot(day_df['timestamp'], day_df['hrv_rmssd'], color='#6c5ce7', linestyle=':', alpha=0.6, label='HRV')
        ax_hrv.set_ylabel("HRV (ms)", color='#6c5ce7', fontsize=11)
        ax_c.set_ylabel("Heart Rate (BPM)", fontsize=11)

        # --- CONTEXT SHADING (Applied to both) ---
        for ax in [ax_g, ax_c]:
            # Shading logic
            for idx in day_df.index:
                row = day_df.loc[idx]
                t = row['timestamp']
                t_end = t + pd.Timedelta(minutes=5)
                
                if row['event_type'] == "SLEEP":
                    ax.axvspan(t, t_end, color='#2d3436', alpha=0.3)
                elif row['event_type'] == "WORKOUT":
                    ax.axvspan(t, t_end, color='#fdcb6e', alpha=0.15)
                elif row['is_outdoor']:
                    ax.axvspan(t, t_end, color='#0984e3', alpha=0.1)

            ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.grid(True, alpha=0.1)

        if i == 0:
            ax_g.legend(loc='upper right', ncol=2)
            ax_c.legend(loc='upper right')

    if output_path:
        plt.savefig(output_path, bbox_inches='tight')
        print(f"Plot Saved: {output_path}")
    else:
        plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", help="Forecast CSV path")
    parser.add_argument("-o", "--output", help="Output PNG path")
    args = parser.parse_args()
    
    csv_file = Path(args.csv)
    if not args.output:
        output_file = csv_file.with_suffix('.png')
    else:
        output_file = Path(args.output)
        
    plot_forecast(str(csv_file), str(output_file))
