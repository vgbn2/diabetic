"""
gauge_accuracy.py — Visual Projection Validator
================================================
Renders a PDF page and overlays extracted data points as coloured dots
to visually confirm temporal/scale alignment.

Usage:
    python -m diabetic.ingestion.offline.parsers.high_res.gauge_accuracy \
        <pdf_path> <csv_path> [--page 0] [--out gauge_output.png]

Metrics produced:
  - Temporal Jitter   : std-dev of minute-gaps (lower = better)
  - Coverage          : % of expected 5-min slots populated
  - Scale Confidence  : labelled (ms source) from calibrator
  - Visual PNG overlay: Red circles = extracted, Yellow = events
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import cv2
    import pypdfium2 as pdfium
    _HAS_CV = True
except ImportError:
    _HAS_CV = False


_DPI = 300
_SCALE = _DPI / 72.0


def render_page_bgr(pdf_path: Path, page_idx: int = 0) -> "np.ndarray":
    """Render a single PDF page to a BGR numpy image at _DPI."""
    doc  = pdfium.PdfDocument(str(pdf_path))
    page = doc[page_idx]
    from PIL import Image
    bmp  = page.render(scale=_SCALE)
    pil  = bmp.to_pil().convert("RGB")
    img  = np.array(pil)
    return cv2.cvtColor(img, cv2.COLOR_RGB2BGR)


def pts_to_pixels(x: float, y: float, page_height_pts: float) -> tuple[int, int]:
    """Convert PDF point coordinates to pixel coordinates."""
    px = int(x * _SCALE)
    py = int((page_height_pts - y) * _SCALE)   # flip Y (PDF origin is bottom-left)
    return px, py


def overlay_csv(
    img: "np.ndarray",
    df: pd.DataFrame,
    page_height_pts: float,
    x_col: str = "x_pts",
    y_col: str = "y_pts",
    glucose_col: str = "glucose",
) -> "np.ndarray":
    """Draw extracted points onto the rendered image."""
    out = img.copy()
    for _, row in df.iterrows():
        if not (x_col in row and y_col in row):
            continue
        px, py = pts_to_pixels(row[x_col], row[y_col], page_height_pts)
        is_event = pd.isna(row.get(glucose_col, float("nan")))
        color = (0, 200, 255) if is_event else (0, 0, 255)  # yellow vs red
        cv2.circle(out, (px, py), 3, color, -1)
    return out


def compute_metrics(df: pd.DataFrame) -> dict:
    """Calculate temporal jitter and coverage stats."""
    glu = df[df["glucose"].notna()].copy()
    glu["ts"] = pd.to_datetime(glu["timestamp"])
    glu = glu.sort_values("ts")

    gaps = glu["ts"].diff().dt.total_seconds().dropna() / 60.0
    jitter = float(gaps.std()) if len(gaps) > 1 else 0.0

    # Coverage: how many 5-min slots are filled over the range?
    if len(glu) > 1:
        total_minutes = (glu["ts"].max() - glu["ts"].min()).total_seconds() / 60.0
        expected_slots = max(1, int(total_minutes / 5))
        coverage = min(1.0, len(glu) / expected_slots)
    else:
        coverage = 0.0

    return {
        "rows_total": len(df),
        "glucose_rows": len(glu),
        "event_rows": len(df) - len(glu),
        "temporal_jitter_min": round(jitter, 2),
        "coverage_pct": round(coverage * 100, 1),
        "duplicate_timestamps": int(df["timestamp"].duplicated().sum()),
    }


def print_report(metrics: dict, csv_path: Path):
    print("\n" + "=" * 56)
    print(f"  GAUGE REPORT — {csv_path.name}")
    print("=" * 56)
    print(f"  Total rows          : {metrics['rows_total']}")
    print(f"  Glucose rows        : {metrics['glucose_rows']}")
    print(f"  Event markers       : {metrics['event_rows']}")
    print(f"  Duplicate timestamps: {metrics['duplicate_timestamps']}")
    print(f"  Temporal jitter     : {metrics['temporal_jitter_min']} min")
    print(f"  Coverage (5-min)    : {metrics['coverage_pct']}%")

    # Verdict
    ok = (
        metrics["duplicate_timestamps"] == 0
        and metrics["temporal_jitter_min"] < 10
        and metrics["coverage_pct"] > 20
    )
    verdict = "PASS" if ok else "FAIL"
    print(f"\n  Verdict : [{verdict}]")
    print("=" * 56 + "\n")
    return ok


def run(
    pdf_path: Path,
    csv_path: Path,
    page_idx: int = 0,
    out_path: Path = Path("gauge_output.png"),
):
    df = pd.read_csv(csv_path)
    metrics = compute_metrics(df)
    print_report(metrics, csv_path)

    if not _HAS_CV:
        print("[gauge] OpenCV / pypdfium2 not available — skipping PNG overlay.")
        return metrics

    img = render_page_bgr(pdf_path, page_idx)

    # Get page height in pts for coordinate flip
    import pypdfium2 as pdfium
    doc  = pdfium.PdfDocument(str(pdf_path))
    page = doc[page_idx]
    page_height_pts = page.get_height()

    # We need x_pts / y_pts columns — if not present, try to reconstruct
    # from timestamp relative position (crude but useful for rough validation)
    if "x_pts" not in df.columns:
        glu = df[df["glucose"].notna()].copy()
        glu["ts"] = pd.to_datetime(glu["timestamp"])
        glu["frac"] = (glu["ts"] - glu["ts"].dt.normalize()) / pd.Timedelta(hours=24)
        # Estimate x from page width and temporal fraction
        pw = page.get_width()
        margin_l, margin_r = 50, pw - 30
        glu["x_pts"] = margin_l + glu["frac"] * (margin_r - margin_l)
        # Estimate y from glucose value (rough — assumes standard scale)
        zero_y_est = page_height_pts * 0.20
        ppm_est = 1.38
        glu["y_pts"] = zero_y_est + glu["glucose"] * ppm_est
        df = glu

    out = overlay_csv(img, df, page_height_pts)
    cv2.imwrite(str(out_path), out)
    print(f"[gauge] Overlay saved -> {out_path}")
    return metrics


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Gauge extraction accuracy")
    ap.add_argument("pdf",  type=Path, help="Source PDF")
    ap.add_argument("csv",  type=Path, help="Extracted CSV")
    ap.add_argument("--page", type=int, default=0)
    ap.add_argument("--out", type=Path, default=Path("gauge_output.png"))
    args = ap.parse_args()
    run(args.pdf, args.csv, args.page, args.out)
