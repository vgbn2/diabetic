import pdfplumber
import sys

def check_pages(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").lower()
            kind = "unknown"
            if "nhật ký" in text or "daily log" in text:
                kind = "DAILY_LOG"
            elif "agp" in text or "profile" in text:
                kind = "AGP_SUMMARY"
            print(f"Page {i+1}: {kind}")


if __name__ == "__main__":
    check_pages(sys.argv[1])
