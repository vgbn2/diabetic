"""
high_res_parser.py — Legacy Wrapper (Phase 1.5 Refactor)
=========================================================
This file is now a thin wrapper around the modularised 
diabetic.ingestion.offline.parsers.high_res package.
"""
from pathlib import Path
from diabetic.ingestion.offline.parsers.high_res import HighResParser

class HighResGlucoseParser:
    """
    Legacy class name for backward compatibility.
    Redirects all calls to the modular HighResParser (v2).
    """
    def __init__(self, pdf_path):
        self.pdf_path = Path(pdf_path)
        self.parser = HighResParser(self.pdf_path)

    def parse(self):
        """Orchestrates the modular parse and returns data points as a list of dicts."""
        self.parser.parse()
        # The new parser stores records in self.parser._records
        return self.parser._records

    def save_csv(self, output_path, **kwargs):
        """Redirects to the modular save_csv logic."""
        return self.parser.save_csv(output_path, **kwargs)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", help="Path to Ottai PDF")
    parser.add_argument("--out", default="metabolic_data.csv", help="Output CSV path")
    args = parser.parse_args()

    wrapper = HighResGlucoseParser(args.pdf)
    wrapper.parse()
    wrapper.save_csv(args.out)
