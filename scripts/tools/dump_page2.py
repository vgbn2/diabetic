"""Dump word layout for a two-date page to understand row grouping."""
import pdfplumber
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with pdfplumber.open('data/test/ottai_data/OttaiShare_Report_12Fed-27Fed2026_normalized.pdf') as pdf:
    # Page 2 has Feb 12 + Feb 13
    p = pdf.pages[1]
    cropped = p.within_bbox(p.cropbox)
    words = cropped.extract_words()
    curves = cropped.curves
    
    print("=== Page 2 (Feb 12 + Feb 13) ===")
    print(f"Page height: {p.height:.1f}")
    print(f"Words: {len(words)}, Curves: {len(curves)}")
    print()
    
    print("--- Words sorted by Y ---")
    for w in sorted(words, key=lambda x: x['top']):
        y = w['top']
        x = w['x0']
        t = w['text']
        # filter to ASCII-safe
        if all(ord(c) < 128 for c in t):
            print(f"  y={y:7.1f}  x={x:7.1f}  [{t}]")
    
    print()
    print("--- Curve Y distribution ---")
    curve_tops = sorted([c.get('top', 0) for c in curves])
    if curve_tops:
        # Bucket by 50pt bands
        bands = {}
        for y in curve_tops:
            band = int(y // 50) * 50
            bands[band] = bands.get(band, 0) + 1
        for band in sorted(bands):
            print(f"  y={band:4d}-{band+50:4d}: {bands[band]:3d} curves")
    
    # Also check page 3 (single day - Feb 14)
    print()
    print("=== Page 3 (Feb 14) ===")
    p3 = pdf.pages[2]
    cropped3 = p3.within_bbox(p3.cropbox)
    words3 = cropped3.extract_words()
    curves3 = cropped3.curves
    print(f"Page height: {p3.height:.1f}")
    print(f"Words: {len(words3)}, Curves: {len(curves3)}")
    print()
    print("--- Words sorted by Y ---")
    for w in sorted(words3, key=lambda x: x['top']):
        y = w['top']
        x = w['x0']
        t = w['text']
        if all(ord(c) < 128 for c in t):
            print(f"  y={y:7.1f}  x={x:7.1f}  [{t}]")
