# RESEARCH.md - Parser Ingestion Diagnostics

## Problem Statement
The Unified Parser is currently failing to extract accurate glucose curves from "Normal" and "Share" reports despite successfully detecting metabolic icons.

## Findings
1.  **Coordinate Ghosting**: Normalized PDFs (from `OttaiShare`) preserve global Y-coordinates. Pages 2-17 contain data at Y < 0 or Y > 1000. The parser was filtering these out or double-counting them in overlaps.
2.  **Scale Failure**: "Normal" reports often display sparse labels. If only a '10' label is found, the parser lacks a zero-point or second reference to calibrate pixels-to-mmol/L conversion accurately.
3.  **BBox Masking**: `pdfplumber` by default sees everything in the document's content stream. Using `CropBox` in the normalizer is not enough; we must use `.within_bbox(page.cropbox)` during extraction to prune "invisible" data.

## Proposed Strategy
- **Layer 1**: Implement `StrictBBox` extraction using `.within_bbox()`. This simplifies deduplication entirely by making it inherent to the page boundary.
- **Layer 2**: Implement `GlobalScaleScanner`. If a chart row lacks labels, scan the entire page for '0', '10', '30' markers and project them onto the row's Y-axis.
- **Layer 3**: Coordinate Translation. Adjust `icon_detector` coordinates to account for the MediaBox-to-CropBox offset in normalized PDFs.
