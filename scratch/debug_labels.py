import pdfplumber
import sys

def check_labels(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        marks = [w for w in words if w['x0'] < 100] # Left margin numbers
        print(f"Numbers in left margin: {len(marks)}")
        for m in marks[:20]:
            safe_text = m['text'].encode('ascii', 'ignore').decode()
            print(f"'{safe_text}' at top={m['top']:.1f}, x0={m['x0']:.1f}")
        
        specific = [w for w in words if w['text'] in ['0', '5', '10', '15', '20']]
        print(f"\nSpecific numeric labels: {len(specific)}")
        for m in specific:
             print(f"'{m['text']}' at top={m['top']:.1f}, x0={m['x0']:.1f}")

if __name__ == "__main__":
    check_labels(sys.argv[1])
