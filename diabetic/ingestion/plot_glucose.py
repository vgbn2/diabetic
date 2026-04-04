import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import argparse
import numpy as np
from pathlib import Path
from datetime import timedelta
import math
from scipy.interpolate import PchipInterpolator

def plot_glucose_data(csv_path, output_image=None, days_to_show=None, smooth_window=None):
    """
    Plots high-resolution glucose data with smoothing and optional split view.
    """
    plt.style.use('seaborn-v0_8-whitegrid')
    print(f"Plotting data from: {csv_path}")
    
    # Load data (Pixel-Dense: No duplicate dropping here)
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    if days_to_show is not None:
        last_date = df['timestamp'].max()
        start_date = last_date - pd.Timedelta(days=days_to_show)
        df = df[df['timestamp'] >= start_date]

    if df.empty:
        print("ERROR: No data to plot.")
        return

    # Determine Layout (5-Day Panels)
    # Use 5-day windows as requested for high-resolution metabolic study
    latest = df['timestamp'].max()
    earliest = df['timestamp'].min()
    total_span_days = max(1, (latest - earliest).days + 1)
    num_panels = math.ceil(total_span_days / 5.0)
    
    fig, axes = plt.subplots(num_panels, 1, figsize=(18, 6 * num_panels), dpi=250)
    if num_panels == 1:
        axes = [axes]
        
    plot_segments = []
    # Start windows from the beginning of the earliest day
    window_start = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
    
    for i in range(num_panels):
        window_end = window_start + pd.Timedelta(days=5)
        segment_data = df[(df['timestamp'] >= window_start) & (df['timestamp'] < window_end)]
        
        # Human readable title
        d_start = window_start.strftime('%b %d')
        d_end = (window_end - pd.Timedelta(seconds=1)).strftime('%b %d')
        title = f"Metabolic Dynamics: {d_start} - {d_end} (Pixel-Dense High Res)"
            
        plot_segments.append((axes[i], segment_data, title))
        window_start = window_end

    for ax, data, title in plot_segments:
        if data.empty: 
            ax.set_title(f"{title} (No Data In This Window)", alpha=0.5)
            continue
        
        # Sort and handle any exact collisions
        # Drop NaNs for the glucose trace specifically to avoid PCHIP failure
        data_clean = data.dropna(subset=['glucose']).groupby('timestamp')['glucose'].mean().reset_index()
        data_clean = data_clean.sort_values('timestamp').reset_index(drop=True)
        
        # 1. Main Trace: Pixel-Perfect Reconstruction with Gap Guard
        # If gap > 1 hour, we break the line by inserting NaNs or plotting segments
        # To avoid 'long lines', we find indices of large gaps
        data_clean['gap'] = data_clean['timestamp'].diff() > pd.Timedelta(hours=1)
        gap_indices = data_clean.index[data_clean['gap']].tolist()
        
        start_idx = 0
        for gap_idx in gap_indices + [len(data_clean)]:
            segment = data_clean.iloc[start_idx:gap_idx]
            if segment.empty: continue
            
            # Plot the segment
            ax.plot(segment['timestamp'], segment['glucose'], color='#0984e3', 
                    linewidth=2.8, alpha=0.9, zorder=5, label='Glucose (Pixel-Dense Trace)' if start_idx == 0 else "")
            
            # Subtle 'Pixel' Scatter
            ax.scatter(segment['timestamp'], segment['glucose'], color='#0984e3', 
                      s=12, alpha=0.15, edgecolors='none', zorder=6)
            
            # High-Fidelity Curvy Overlay (PCHIP) - only for segments with enough data
            if len(segment) > 10:
                try:
                    x = mdates.date2num(segment['timestamp'])
                    y = segment['glucose'].values
                    x_new = np.linspace(x.min(), x.max(), min(3000, len(segment)*10))
                    pchip = PchipInterpolator(x, y)
                    y_smooth = pchip(x_new)
                    x_dates = mdates.num2date(x_new)
                    
                    ax.plot(x_dates, y_smooth, color='#0984e3', linewidth=1.5, alpha=0.6, 
                            linestyle='-', zorder=4)
                except Exception:
                    pass # Fallback to raw segment if interpolation fails
            
            start_idx = gap_idx


        # Target Range (3.9 - 10.0)
        ax.axhspan(3.9, 10.0, color='#00b894', alpha=0.12, label='Ideal Target Range')
        
        # Threshold Lines
        ax.axhline(10.0, color='#d63031', linestyle=':', alpha=0.5, linewidth=1.5, label='Hyperglycemia (>10.0)')
        ax.axhline(3.9, color='#e17055', linestyle=':', alpha=0.5, linewidth=1.5, label='Hypoglycemia (<3.9)')

        # Vertical Midnight Markers
        # Annotate Daily Highs and Lows
        unique_days = pd.to_datetime(data_clean['timestamp'].dt.date).unique()
        for day in unique_days:
            day_data = data_clean[data_clean['timestamp'].dt.date == day.date()]
            if not day_data.empty:
                idxmax = day_data['glucose'].idxmax()
                idxmin = day_data['glucose'].idxmin()
                
                t_max = day_data.loc[idxmax, 'timestamp']
                g_max = day_data.loc[idxmax, 'glucose']
                t_min = day_data.loc[idxmin, 'timestamp']
                g_min = day_data.loc[idxmin, 'glucose']
                
                # High Label
                ax.annotate(f"{g_max:.1f}", xy=(mdates.date2num(t_max), g_max),
                            xytext=(0, 10), textcoords='offset points', ha='center', va='bottom',
                            fontsize=9, fontweight='bold', color='white',
                            bbox=dict(boxstyle="round,pad=0.3", fc="#d63031", ec="none", alpha=0.9), zorder=10)
                            
                # Low Label
                ax.annotate(f"{g_min:.1f}", xy=(mdates.date2num(t_min), g_min),
                            xytext=(0, -10), textcoords='offset points', ha='center', va='top',
                            fontsize=9, fontweight='bold', color='white',
                            bbox=dict(boxstyle="round,pad=0.3", fc="#e17055", ec="none", alpha=0.9), zorder=10)

        # 3. Metabolic Pivot Icons (Wave 6)
        # We plot these on the actual glucose trace background
        pivots = data[data['bolus'] > 0 | (data['basal'] > 0) | (data['meal'] > 0)]
        if not pivots.empty:
            # Bolus
            bolus_data = data[data['bolus'] > 0]
            if not bolus_data.empty:
                ax.scatter(bolus_data['timestamp'], [max(data_clean['glucose']) + 1.5] * len(bolus_data), 
                           marker='v', color='#fd79a8', s=120, label='Bolus (Insulin)', zorder=11)
            
            # Meals
            meal_data = data[data['meal'] > 0]
            if not meal_data.empty:
                ax.scatter(meal_data['timestamp'], [max(data_clean['glucose']) + 0.8] * len(meal_data), 
                           marker='^', color='#fdcb6e', s=120, label='Meal (Carbs)', zorder=11)

            # Basal
            basal_data = data[data['basal'] > 0]
            if not basal_data.empty:
                ax.scatter(basal_data['timestamp'], [max(data_clean['glucose']) + 2.2] * len(basal_data), 
                           marker='*', color='#00cec9', s=100, label='Basal Marker', zorder=11, alpha=0.6)

            midnight = pd.Timestamp(day)
            ax.axvline(midnight, color='#2d3436', linestyle='--', alpha=0.3, linewidth=1, zorder=1)

        # Labels and Titles
        ax.set_title(title, fontsize=16, fontweight='bold', pad=15, color='#2d3436')
        ax.set_ylabel("Glucose (mmol/L)", fontsize=13, fontweight='medium')
        
        # Explicit Date/Time Anchors (6-hour increments) - UNIFORMLY ON ALL PANELS
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%a %d, %H:%M'))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1)) 
        
        # Force label visibility even on non-bottom panels
        ax.tick_params(labelbottom=True)
        
        ax.grid(True, which='major', linestyle='-', alpha=0.25)
        ax.grid(True, which='minor', linestyle=':', alpha=0.15)
        max_g = data_clean['glucose'].max() if not data_clean.empty else 10.0
        ax.set_ylim(0, max(max_g + 3, 16))

    plt.gcf().autofmt_xdate()
    
    # Shared Legend at bottom
    handles, labels = plot_segments[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', bbox_to_anchor=(0.5, 0.02), 
               ncol=4, fontsize=11, frameon=True, facecolor='white')

    plt.tight_layout(rect=[0, 0.05, 1, 0.98])

    if output_image:
        plt.savefig(output_image, dpi=300, bbox_inches='tight')
        print(f"Enhanced graph saved to: {output_image}")
    else:
        plt.show()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot high-resolution glucose data.")
    parser.add_argument("csv", help="Path to the high-resolution glucose CSV file")
    parser.add_argument("--output", "-o", help="Save the plot to an image file")
    parser.add_argument("--days", "-d", type=int, default=None, help="Number of days to display (None for all)")
    parser.add_argument("--smooth", "-s", type=int, default=5, help="Smoothing window size (default: 5)")
    
    args = parser.parse_args()
    
    if not Path(args.csv).exists():
        print(f"Error: File not found {args.csv}")
    else:
        plot_glucose_data(args.csv, args.output, args.days, args.smooth)
