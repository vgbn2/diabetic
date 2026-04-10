import pdfplumber
from pypdf import PdfReader, PdfWriter
from pathlib import Path
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
        
        raw_headers.sort()
        deduped_headers = []
        if raw_headers:
            deduped_headers.append(raw_headers[0])
            for h in raw_headers[1:]:
                if h - deduped_headers[-1] > 300: # charts are roughly 350-450 pts tall
                    deduped_headers.append(h)
        
        split_points = [0]
        if len(deduped_headers) > 1:
            # Use headers as split points
            for h in deduped_headers:
                split_points.append(h - 10)
            split_points.append(full_height)
        else:
            # FALLBACK: Fixed height splitting for long 'Share' pages
            print(f"  Warning: Insufficient headers for {pdf_path.name}. Using fixed-height geometry.")
            current_y = daily_log_y if daily_log_y > 0 else 0
            if current_y > 100: split_points.append(current_y)
            
            # Standard Ottai charts are ~420pts tall. 
            # We split every 421pts to avoid cutting through the middle of a row.
            while current_y < full_height:
                current_y += 421 
                split_points.append(min(current_y, full_height))

    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    source_page = reader.pages[0]
    
    for i in range(len(split_points)-1):
        new_page = writer.add_page(source_page)
        
        top = float(split_points[i])
        bottom = float(split_points[i+1])
        
        # Apply 20pt overlap except for boundaries
        effective_top = max(0, top - (20 if i > 0 else 0))
        effective_bottom = min(full_height, bottom + (20 if i < len(split_points)-2 else 0))
        
        pypdf_bottom = full_height - effective_bottom
        pypdf_top = full_height - effective_top
        
        # Crop exactly to the segment
        new_page.mediabox.lower_left = (0, pypdf_bottom)
        new_page.mediabox.upper_right = (full_width, pypdf_top)
        new_page.cropbox.lower_left = (0, pypdf_bottom)
        new_page.cropbox.upper_right = (full_width, pypdf_top)

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
