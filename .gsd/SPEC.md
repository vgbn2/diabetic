# SPEC.md - Unified Metabolic Parser [FINALIZED]

## Goal
Establish a 100% stable, high-fidelity metabolic ingestion pipeline for Ottai clinical reports.

## Requirements
- **Multi-Modal**: Support both "Normal" (multi-page) and "Share" (long-scroll) reports.
- **Vision-Vector Sync**: Merge vector-based curve data with vision-based metabolic markers (Bolus, Basal, Meal).
- **Coordinate Integrity**: 100% accurate temporal mapping of data points to 5-minute resolutions.
- **Scale Calibration**: Automated detection of glucose units (mmol/L) and vertical axes.

## Constraints
- **Zero Duplication**: Ensure ghost points from overlapping pages are eliminated.
- **Terminals**: Use cp1252-safe output (ASCII arrows only).
- **Performance**: High-res rendering (576 DPI) must be optimized for multi-page parsing.
