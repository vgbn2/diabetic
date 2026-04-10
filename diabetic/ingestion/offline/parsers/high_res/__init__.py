"""
High-res modular parser package.

Quick usage:
    from diabetic.ingestion.offline.parsers.high_res import HighResParser

    parser = HighResParser("report.pdf")
    parser.parse()
    parser.save_csv("out.csv")
"""
from .orchestrator import HighResParser

__all__ = ["HighResParser"]
