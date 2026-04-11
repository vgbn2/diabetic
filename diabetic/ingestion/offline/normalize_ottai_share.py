from pathlib import Path
import pdfplumber
from pypdf import PdfReader, PdfWriter, Transformation
import sys

def normalize_share_report(pdf_path, output_path=None):
    if output_path is None:
        output_path = pdf_path.parent / f"{pdf_path.stem}_normalized.pdf"
    
    print(f"Normalizing: {pdf_path.name}")
    
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        full_height = float(page.height)
        full_width = float(page.width)
        words = page.extract_words()
        
        daily_log_y = 0
        # More robust keywords for start of logs
        keywords = ["Nhật", "ký", "Báo", "cáo", "Thứ", "Ngày"]
        for i, word in enumerate(words):
            if any(k in word['text'] for k in keywords):
                daily_log_y = max(0, word['top'] - 50)
                break
        
        raw_headers = []
        # Pattern: "Thứ X, dd ThXX 20XX" or similar
        for i in range(len(words)-1):
            w1 = words[i]['text']
            w2 = words[i+1]['text']
            # Look for years or months with commas
            if (',' in w1 or ',' in w2) and any(y in (w1+w2) for y in ['2023','2024', '2025', '2026']):
                raw_headers.append(words[i]['top'])
            # Look for Vietnamese date markers
            if "Th" in w1 and any(y in w2 for y in ['2023','2024', '2025', '2026']):
                raw_headers.append(words[i]['top'])
        
        # Find wide horizontal lines (>70% width)
        h_lines = [l for l in page.lines if abs(l['top'] - l['bottom']) < 1 and l['width'] > (full_width * 0.7)]
        
        # Unified Splitting Strategy: Dates + Wide Horizontal Lines
        all_candidates = raw_headers + [l['top'] for l in h_lines]
        all_candidates.sort()
        
        deduped = []
        if all_candidates:
            deduped.append(all_candidates[0])
            for c in all_candidates[1:]:
                # charts are at least 350-500 pts tall in daily views
                if c - deduped[-1] > 350: 
                    deduped.append(c)
        
        # SCROLL DETECTION FALLBACK
        # If the page is a "Giant Scroll" (e.g. 3000pt) and we found < 3 markers, force split
        if full_height > 1000 and len(deduped) < 3:
            print(f"  [Scroll Detected] Force splitting every 500pt...")
            deduped = list(range(450, int(full_height), 480))
            
        split_points = [0]
        for d in deduped:
            if d > 100: # Avoid splitting the very top header
                # Ensure we don't split too early
                if not split_points or (d - split_points[-1] > 300):
                    split_points.append(d - 30) # 30pt margin for headers
        
        if not split_points or split_points[-1] < full_height - 300:
            split_points.append(full_height)
        
        print(f"  Generated {len(split_points)-1} segments (Height Pattern: {[int(split_points[i+1]-split_points[i]) for i in range(len(split_points)-1)]})")

    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    source_page = reader.pages[0]
    
    for i in range(len(split_points)-1):
        top = float(split_points[i])
        bottom = float(split_points[i+1])
        
        # Apply 15pt overlap to catch boundary labels
        eff_top = max(0, top - 15)
        eff_bottom = min(full_height, bottom + 15)
        eff_height = eff_bottom - eff_top
        
        # Create a clean page with the segment height
        new_page = writer.add_blank_page(width=full_width, height=eff_height)
        
        # Construct transformation: shift the source segment to (0,0)
        # pdfplumber y is from top (0 at top). 
        # pypdf y is from bottom (0 at bottom).
        shift_y = -(full_height - eff_bottom)
        
        new_page.merge_page(source_page)
        new_page.add_transformation(Transformation().translate(0, shift_y))
        
        # Set all boxes to (0, 0, width, height)
        new_page.mediabox.lower_left = (0, 0)
        new_page.mediabox.upper_right = (full_width, eff_height)
        new_page.cropbox.lower_left = (0, 0)
        new_page.cropbox.upper_right = (full_width, eff_height)

    with open(output_path, "wb") as f:
        writer.write(f)
    print(f"  Success: Generated {output_path.name} ({len(writer.pages)} pages)")
    return output_path


if __name__ == "__main__":
    data_dir = Path("data/test/ottai_data")
    for pdf_file in data_dir.glob("*OttaiShare*.pdf"):
        if "_normalized" in pdf_file.name:
            continue
        try:
            normalize_share_report(pdf_file)
        except Exception as e:
            print(f"  Error processing {pdf_file.name}: {e}")
