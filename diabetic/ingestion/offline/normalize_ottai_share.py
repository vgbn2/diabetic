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
        for i, word in enumerate(words):
            if "Nhật" in word['text'] and i+1 < len(words) and "ký" in words[i+1]['text']:
                daily_log_y = word['top'] - 15
                break
        
        raw_headers = []
        for i in range(len(words)-2):
            text = f"{words[i]['text']} {words[i+1]['text']} {words[i+2]['text']}"
            if ',' in text and any(year in text for year in ['2024', '2025', '2026']):
                y = words[i]['top']
                if y >= daily_log_y:
                    raw_headers.append(y)
        
        raw_headers.sort()
        deduped_headers = []
        if raw_headers:
            deduped_headers.append(raw_headers[0])
            for h in raw_headers[1:]:
                if h - deduped_headers[-1] > 50:
                    deduped_headers.append(h)
        
        split_points = [0]
        if deduped_headers:
            split_points.append(deduped_headers[0] - 5)
            for i in range(len(deduped_headers)-1):
                split_points.append(deduped_headers[i+1] - 5)
            split_points.append(full_height)
        else:
            print(f"  Warning: No headers detected in log section. Using layout fallback.")
            if daily_log_y > 0:
                split_points.append(daily_log_y)
            
            current_y = split_points[-1]
            while current_y < full_height:
                current_y += 842 
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
