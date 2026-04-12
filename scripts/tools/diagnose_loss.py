"""
Data loss diagnosis script.
Checks the normalized PDFs page-by-page to understand the two-days-per-page layout
and identify why alternating days have near-zero extraction.
"""
import pdfplumber
import re
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

VN_MONTH = {
    "th01": 1, "th1": 1, "thg 1": 1, "thg 01":1,
    "th02": 2, "th2": 2, "thg 2": 2, "thg 02":2,
    "th03": 3, "th3": 3, "thg 3": 3, "thg 03":3,
    "th04": 4, "th4": 4, "thg 4": 4, "thg 04":4,
    "th05": 5, "th5": 5, "thg 5": 5, "thg 05":5,
    "th06": 6, "th6": 6, "thg 6": 6, "thg 06":6,
    "th07": 7, "th7": 7, "thg 7": 7, "thg 07":7,
    "th08": 8, "th8": 8, "thg 8": 8, "thg 08":8,
    "th09": 9, "th9": 9, "thg 9": 9, "thg 09":9,
    "th10": 10, "thg 10": 10,
    "th11": 11, "thg 11": 11,
    "th12": 12, "thg 12": 12,
}

_DATE_PATTERN = re.compile(
    r"(\d{1,2})[-/\s]+((?:th\d{2}|thg\s+\d{1,2}|th\d{1,2}|jan|feb|fed|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|tháng\s+\d{1,2}))(?:[-/\s]+(\d{4}))?",
    re.IGNORECASE
)

pdfs = [
    ("feb12-feb27-2026", "data/test/ottai_data/OttaiShare_Report_12Fed-27Fed2026_normalized.pdf"),
    ("mar23-apr07-2026", "data/test/ottai_data/OttaiShare_Report_23Mar-7Apr2026_normalized.pdf"),
    ("june02-june17-2025", "data/test/ottai_data/OttaiShare_Report_2June-17June2025_normalized.pdf"),
]

for name, path in pdfs:
    print(f"\n{'='*60}")
    print(f"PDF: {name}")
    print(f"{'='*60}")
    try:
        with pdfplumber.open(path) as pdf:
            print(f"Total pages: {len(pdf.pages)}")
            for i, p in enumerate(pdf.pages):
                words = p.extract_words()
                h = round(p.height, 1)
                w = round(p.width, 1)
                
                # Find all date-like tokens with their Y positions
                recon = " ".join(wd["text"] for wd in words)
                dates_found = []
                for m in _DATE_PATTERN.finditer(recon):
                    day = m.group(1)
                    month_str = m.group(2).lower().strip()
                    # Resolve month
                    month = VN_MONTH.get(month_str)
                    if not month:
                        emap = {"jan":1,"feb":2,"fed":2,"mar":3,"apr":4,"may":5,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
                        for k,v in emap.items():
                            if k in month_str:
                                month = v
                                break
                    if month:
                        dates_found.append(f"{month:02d}-{int(day):02d}")
                
                # Count glucose-colored curves
                glucose_curves = 0
                for c in p.curves:
                    col = c.get("stroking_color") or c.get("non_stroking_color")
                    if isinstance(col, (list, tuple)) and len(col) >= 3:
                        r, g, b = float(col[0]), float(col[1]), float(col[2])
                        if (b > 0.8 and g > 0.3 and r < 0.4):  # Blue glucose
                            glucose_curves += 1
                
                unique_dates = sorted(set(dates_found))
                print(f"  Page {i+1:2d} | h={h:6.1f} w={w:5.1f} | words={len(words):3d} curves={len(p.curves):4d} glucose_blue={glucose_curves:3d} | dates={unique_dates}")
    except Exception as e:
        print(f"  ERROR: {e}")
