import pdfplumber
import numpy as np
from pathlib import Path
import re

def debug_pdf(pdf_path):
    print(f"DEBUGGING: {pdf_path}")
    with pdfplumber.open(pdf_path) as pdf:
        # Check first page
        page = pdf.pages[0]
        curves = page.curves
        print(f"Page 0: {len(curves)} curves found.")
        
        # Look for colors
        colors = {}
        for c in curves:
            col = str(c.get('non_stroking_color') or c.get('stroking_color'))
            colors[col] = colors.get(col, 0) + 1
        
        print("Colors found in curves:")
        for col, count in colors.items():
            print(f"  {col}: {count}")

        # Look for glucose labels
        words = page.extract_words()
        glucose_labels = [w for w in words if w['text'] in ['0', '10', '30']]
        print(f"Glucose labels found: {len(glucose_labels)}")
        for l in glucose_labels[:5]:
            print(f"  '{l['text']}' at x={l['x0']:.1f}, y={l['top']:.1f}")

        # Check date headers
        date_pattern = r"\b(\d{1,2}\s+(?:Th\d{2}|thg\s+\d{1,2}))\b"
        text = page.extract_text() or ""
        matches = list(re.finditer(date_pattern, text))
        print(f"Date headers found by text: {len(matches)}")

if __name__ == "__main__":
    debug_pdf("data/test/ottai_data/Ottai_Report_07-04-2026_9954.pdf")
    print("-" * 30)
    # Check a Normalized page
    norm_path = Path("data/test/ottai_data/OttaiShare_Report_23Mar-7Apr2026_normalized.pdf")
    if norm_path.exists():
        debug_pdf(norm_path)
