import pdfplumber
import pandas as pd
from pathlib import Path

def analyze_pdf(path):
    p = Path(path)
    if not p.exists():
        print(f"File not found: {path}")
        return
    print(f"\n--- Analyzing: {path} ---")
    with pdfplumber.open(path) as pdf:
        # Check first 3 pages
        for p_idx in range(min(3, len(pdf.pages))):
            page = pdf.pages[p_idx]
            print(f"\nPage {p_idx+1}:")
            words = page.extract_words()
            # Find common time and glucose labels
            labels = [w for w in words if w['text'] in ['00:00', '0:00', '12:00', '24:00', '0', '10', '30']]
            for l in labels:
                print(f"  Label: {l['text']} at x0={l['x0']:.2f}, top={l['top']:.2f}")
            
            # Analyze some curves
            curves = page.curves
            print(f"  Total curves: {len(curves)}")
            for i, c in enumerate(curves[:15]):
                color = c.get('stroking_color') or c.get('non_stroking_color')
                pts = c.get('pts', [])
                if not pts: continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                width = max(xs) - min(xs)
                height = max(ys) - min(ys)
                print(f"  Curve {i}: Color={color}, W={width:.2f}, H={height:.2f}, Pts={len(pts)}")

base_path = Path(r"C:\Users\Lenovo\Desktop\VGBN\.vscode\CODEPTIT\hyperglycemia-faint-predictor\data\renderings")
analyze_pdf(base_path / 'OttaiShare_Report_2June-17June2025.pdf')
analyze_pdf(base_path / 'OttaiShare_Report_12Fed-27Fed2026.pdf')
