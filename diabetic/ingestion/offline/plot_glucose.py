import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import argparse
import numpy as np
from pathlib import Path
import math


def plot_glucose_data(csv_path, output_image=None, days_to_show=None, smooth_window=None):
    plt.style.use('seaborn-v0_8-whitegrid')
    print(f"plotting data from: {csv_path}")

    df = pd.read_csv(csv_path)
    
    # --- UNIVERSAL COLUMN MAPPING ---
    # Map forecast/live columns to standard plotting names
    col_map = {
        'timestamp_utc': 'timestamp',
        'glucose_mmol_l': 'glucose',
        'insulin_units': 'bolus',
        'meal_carbs': 'meal'
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Ensure standard columns exist, even if empty
    for col in ['bolus', 'meal', 'basal']:
        if col not in df.columns:
            df[col] = 0.0

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')

    if days_to_show is not None:
        last_date = df['timestamp'].max()
        df = df[df['timestamp'] >= last_date - pd.Timedelta(days=days_to_show)]

    if df.empty:
        print("error: no data to plot.")
        return

    latest           = df['timestamp'].max()
    earliest         = df['timestamp'].min()
    total_span_days  = max(1, (latest - earliest).days + 1)
    num_panels       = math.ceil(total_span_days / 5.0)

    fig, axes = plt.subplots(num_panels, 1, figsize=(18, 6 * num_panels), dpi=250)
    if num_panels == 1:
        axes = [axes]

    plot_segments = []
    window_start  = earliest.replace(hour=0, minute=0, second=0, microsecond=0)

    for i in range(num_panels):
        window_end    = window_start + pd.Timedelta(days=5)
        segment_data  = df[(df['timestamp'] >= window_start) & (df['timestamp'] < window_end)]
        
        # Clamp label to actual data bounds to avoid "phantom" future dates
        actual_end    = min(window_end - pd.Timedelta(seconds=1), latest)
        d_start       = window_start.strftime('%b %d')
        d_end         = actual_end.strftime('%b %d')
        
        title         = f"Metabolic Dynamics: {d_start} – {d_end}"
        if d_start == d_end:
            title = f"Metabolic Dynamics: {d_start} (Summary)"
            
        plot_segments.append((axes[i], segment_data, title))
        window_start  = window_end

    for ax, data, title in plot_segments:

        # ── clean glucose trace ────────────────────────────────────────────────
        data_clean = pd.DataFrame()
        if not data.empty:
            # Preserve neural columns if present by taking mean during grouping
            data_clean = (
                data.dropna(subset=['glucose'])
                    .groupby('timestamp').mean(numeric_only=True)
                    .reset_index()
                    .sort_values('timestamp')
                    .reset_index(drop=True)
            )

        has_glucose = not data_clean.empty

        # FIX 1: if there is no glucose trace for this window, mark it clearly
        # and skip all glucose-dependent rendering (annotations, pivot y-positions)
        # instead of rendering an empty chart with floating markers.
        if not has_glucose:
            ax.set_title(f"{title}  —  no glucose data", fontsize=14, color='#888888', pad=12)
            ax.set_ylim(0, 16)
            ax.set_ylabel("Glucose (mmol/L)", fontsize=13)
            ax.axhspan(3.9, 10.0, color='#00b894', alpha=0.08)
            ax.axhline(10.0, color='#d63031', linestyle=':', alpha=0.4, linewidth=1.2)
            ax.axhline(3.9,  color='#e17055', linestyle=':', alpha=0.4, linewidth=1.2)
            ax.grid(True, which='major', linestyle='-', alpha=0.25)
            if not data.empty:
                # still set x range so midnight lines are sensible
                ax.set_xlim(data['timestamp'].min(), data['timestamp'].max())
            ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%a %d, %H:%M'))
            ax.tick_params(axis='x', which='both', labelbottom=True, labelsize=9)
            continue

        # ── gap-aware glucose trace ────────────────────────────────────────────
        data_clean['gap'] = data_clean['timestamp'].diff() > pd.Timedelta(hours=6)
        gap_indices = data_clean.index[data_clean['gap']].tolist()

        start_idx = 0
        for gap_idx in gap_indices + [len(data_clean)]:
            seg = data_clean.iloc[start_idx:gap_idx]
            if seg.empty:
                start_idx = gap_idx
                continue

            ax.plot(seg['timestamp'], seg['glucose'],
                    color='#0984e3', linewidth=2.0, alpha=0.9, zorder=5,
                    label='Glucose (Raw)' if start_idx == 0 else "")
            
            # Neural Overlay (if present)
            if 'glucose_neural' in seg.columns:
                ax.plot(seg['timestamp'], seg['glucose_neural'],
                        color='#6c5ce7', linewidth=2.0, linestyle='--',
                        alpha=0.8, zorder=6,
                        label='CNN Forecast' if start_idx == 0 else "")

            ax.scatter(seg['timestamp'], seg['glucose'],
                       color='#0984e3', s=10, alpha=0.12, edgecolors='none', zorder=6)
            start_idx = gap_idx

        # ── reference bands ───────────────────────────────────────────────────
        ax.axhspan(3.9, 10.0, color='#00b894', alpha=0.12, label='Target range (3.9–10.0)')
        ax.axhline(10.0, color='#d63031', linestyle=':', alpha=0.5, linewidth=1.5,
                   label='Hyperglycemia (>10.0)')
        ax.axhline(3.9,  color='#e17055', linestyle=':', alpha=0.5, linewidth=1.5,
                   label='Hypoglycemia (<3.9)')

        # ── per-day annotations & midnight lines ──────────────────────────────
        unique_days = pd.to_datetime(data_clean['timestamp'].dt.date).unique()
        for day in unique_days:
            day_data = data_clean[data_clean['timestamp'].dt.date == day.date()]
            if day_data.empty:
                continue

            idxmax = day_data['glucose'].idxmax()
            idxmin = day_data['glucose'].idxmin()

            ax.annotate(
                f"{day_data.loc[idxmax, 'glucose']:.1f}",
                xy=(mdates.date2num(day_data.loc[idxmax, 'timestamp']),
                    day_data.loc[idxmax, 'glucose']),
                xytext=(0, 10), textcoords='offset points',
                ha='center', va='bottom', fontsize=9, fontweight='bold', color='white',
                bbox=dict(boxstyle="round,pad=0.3", fc="#d63031", ec="none", alpha=0.9),
                zorder=10,
            )
            ax.annotate(
                f"{day_data.loc[idxmin, 'glucose']:.1f}",
                xy=(mdates.date2num(day_data.loc[idxmin, 'timestamp']),
                    day_data.loc[idxmin, 'glucose']),
                xytext=(0, -10), textcoords='offset points',
                ha='center', va='top', fontsize=9, fontweight='bold', color='white',
                bbox=dict(boxstyle="round,pad=0.3", fc="#e17055", ec="none", alpha=0.9),
                zorder=10,
            )
            ax.axvline(pd.Timestamp(day), color='#2d3436', linestyle='--',
                       alpha=0.3, linewidth=1, zorder=1)

        # ── pivot markers ─────────────────────────────────────────────────────
        # FIX 2: only render pivot markers when there IS a glucose trace.
        # g_max is now always derived from actual data (not the 10.0 fallback),
        # so markers never float in an otherwise empty panel.
        g_max = data_clean['glucose'].max()

        bolus_data = data[data['bolus'] > 0]
        basal_data = data[data['basal'] > 0]
        meal_data  = data[data['meal']  > 0]

        if not bolus_data.empty:
            ax.scatter(bolus_data['timestamp'], [g_max + 1.5] * len(bolus_data),
                       marker='v', color='#fd79a8', s=120, label='Bolus (insulin)', zorder=11)
        if not meal_data.empty:
            ax.scatter(meal_data['timestamp'],  [g_max + 0.8] * len(meal_data),
                       marker='^', color='#fdcb6e', s=120, label='Meal (carbs)', zorder=11)
        if not basal_data.empty:
            ax.scatter(basal_data['timestamp'], [g_max + 2.2] * len(basal_data),
                       marker='*', color='#00cec9', s=100, label='Basal marker',
                       zorder=11, alpha=0.7)

        # ── predictive overlay (XGBoost) ──────────────────────────────────────
        if 'predicted_30m' in data.columns:
            pred_data = data.dropna(subset=['predicted_30m'])
            if not pred_data.empty:
                # We shift the forecast line FORWARD by 30 mins (6 rows) 
                # to overlay it on the actual outcome it was predicting.
                ax.plot(pred_data['timestamp'] + pd.Timedelta(minutes=30), 
                        pred_data['predicted_30m'],
                        color='#e67e22', linestyle='--', linewidth=1.5, alpha=0.8,
                        label='XGBoost 30m Forecast', zorder=12)

        # ── axes & grid ───────────────────────────────────────────────────────
        ax.set_title(title, fontsize=16, fontweight='bold', pad=15, color='#2d3436')
        ax.set_ylabel("Glucose (mmol/L)", fontsize=13)
        ax.set_ylim(0, max(g_max + 3, 16))

        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%a %d, %H:%M'))
        ax.xaxis.set_minor_locator(mdates.HourLocator(interval=1))
        ax.tick_params(axis='x', which='both', labelbottom=True, labelsize=9)

        ax.grid(True, which='major', linestyle='-', alpha=0.3)
        ax.grid(True, which='minor', linestyle=':', alpha=0.15)

    plt.gcf().autofmt_xdate()

    # use first panel with actual glucose data for legend handles
    legend_ax = next(
        (seg[0] for seg in plot_segments if not seg[1].dropna(subset=['glucose']).empty),
        plot_segments[0][0],
    )
    handles, labels = legend_ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', bbox_to_anchor=(0.5, 0.02),
               ncol=5, fontsize=11, frameon=True, facecolor='white')

    plt.tight_layout(rect=[0, 0.05, 1, 0.98])

    if output_image:
        plt.savefig(output_image, dpi=300, bbox_inches='tight')
        print(f"saved to: {output_image}")
    else:
        plt.show()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="plot high-resolution glucose data")
    parser.add_argument("csv",      help="path to glucose CSV")
    parser.add_argument("--output", "-o", help="save plot to image file")
    parser.add_argument("--days",   "-d", type=int, default=None,
                        help="days to display (default: all)")
    parser.add_argument("--smooth", "-s", type=int, default=5,
                        help="smoothing window (default: 5)")
    args = parser.parse_args()

    if not Path(args.csv).exists():
        print(f"error: file not found — {args.csv}")
    else:
        plot_glucose_data(args.csv, args.output, args.days, args.smooth)