import pdfplumber
import os

pdf_path = 'data/test/ottai_data/Ottai_Report_07-04-2026_9954.pdf'
out_path = 'scratch/text_dump.txt'

if os.path.exists(out_path):
    os.remove(out_path)

with pdfplumber.open(pdf_path) as pdf:
    with open(out_path, 'w', encoding='utf-8') as f:
        for i, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").lower()
            f.write(f"Page {i+1}:\n{text[:500]}\n" + "="*50 + "\n")
