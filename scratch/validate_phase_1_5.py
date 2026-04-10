"""Phase 1.5 Empirical Validation Suite"""
import time
import pandas as pd

results = {}

# ====================================================================
# TEST 2: Normal Report Extraction
# ====================================================================
print("=== TEST 2: Normal Report Extraction ===")
from diabetic.ingestion.offline.parsers.high_res import HighResParser

t0 = time.time()
p = HighResParser("data/test/ottai_data/Ottai_Report_07-04-2026_9954.pdf")
p.parse()
p.save_csv("storage/data/processed/Normal_Report_v2.csv")
elapsed = time.time() - t0

df = pd.read_csv("storage/data/processed/Normal_Report_v2.csv")
glu = df[df["glucose"].notna()]

print(f"  Elapsed time     : {elapsed:.1f}s")
print(f"  Total rows       : {len(df)}")
print(f"  Glucose rows     : {len(glu)}")
print(f"  Event rows       : {len(df) - len(glu)}")
dupe_ts = int(df["timestamp"].duplicated().sum())
print(f"  Dupe timestamps  : {dupe_ts}")
print(f"  Glucose min      : {glu.glucose.min():.2f}")
print(f"  Glucose max      : {glu.glucose.max():.2f}")
print(f"  Glucose mean     : {glu.glucose.mean():.2f}")
print(f"  Date range       : {df.timestamp.min()} -> {df.timestamp.max()}")

bad = glu[(glu.glucose < 0.5) | (glu.glucose > 40.0)]
print(f"  Out-of-range pts : {len(bad)}")

df["ts"] = pd.to_datetime(df["timestamp"])
hours = sorted(df["ts"].dt.hour.unique())
print(f"  Unique hours     : {hours}")
all_midnight = all(h == 0 for h in hours)
print(f"  All-midnight bug : {all_midnight}")

t2_pass = (
    len(df) > 50
    and dupe_ts == 0
    and len(bad) == 0
    and not all_midnight
    and elapsed < 60
)
verdict = "PASS" if t2_pass else "FAIL"
print(f"RESULT: {verdict}")
results["T2_Normal"] = verdict
print()

# ====================================================================
# TEST 3: Share Report Extraction
# ====================================================================
print("=== TEST 3: Share Report Extraction ===")

t0 = time.time()
p2 = HighResParser("data/test/ottai_data/OttaiShare_Report_23Mar-7Apr2026.pdf")
p2.parse()
p2.save_csv("storage/data/processed/Share_Mar_Apr_v2.csv")
elapsed2 = time.time() - t0

df2 = pd.read_csv("storage/data/processed/Share_Mar_Apr_v2.csv")
glu2 = df2[df2["glucose"].notna()]

print(f"  Elapsed time     : {elapsed2:.1f}s")
print(f"  Total rows       : {len(df2)}")
print(f"  Glucose rows     : {len(glu2)}")
dupe_ts2 = int(df2["timestamp"].duplicated().sum())
print(f"  Dupe timestamps  : {dupe_ts2}")

if len(glu2) > 0:
    print(f"  Glucose min      : {glu2.glucose.min():.2f}")
    print(f"  Glucose max      : {glu2.glucose.max():.2f}")

df2["ts"] = pd.to_datetime(df2["timestamp"])
hours2 = sorted(df2["ts"].dt.hour.unique())
print(f"  Unique hours     : {hours2}")
all_midnight2 = all(h == 0 for h in hours2)
print(f"  All-midnight bug : {all_midnight2}")

t3_pass = len(df2) > 10 and dupe_ts2 == 0
verdict3 = "PASS" if t3_pass else "FAIL"
print(f"RESULT: {verdict3}")
results["T3_Share"] = verdict3
print()

# ====================================================================
# TEST 4: Gauge Accuracy Tool
# ====================================================================
print("=== TEST 4: Gauge Accuracy Tool ===")
from diabetic.ingestion.offline.parsers.high_res.gauge_accuracy import compute_metrics, print_report
from pathlib import Path

df_gauge = pd.read_csv("storage/data/processed/Normal_Report_v2.csv")
metrics = compute_metrics(df_gauge)
gauge_pass = print_report(metrics, Path("Normal_Report_v2.csv"))

t4_pass = (
    metrics["duplicate_timestamps"] == 0
    and metrics["glucose_rows"] > 50
    and metrics["coverage_pct"] > 20
)
verdict4 = "PASS" if t4_pass else "FAIL"
print(f"RESULT: {verdict4}")
results["T4_Gauge"] = verdict4
print()

# ====================================================================
# TEST 5: Timestamp Collapse Regression
# ====================================================================
print("=== TEST 5: Timestamp Collapse Regression ===")
df_ts = pd.read_csv("storage/data/processed/Normal_Report_v2.csv")
df_ts["ts"] = pd.to_datetime(df_ts["timestamp"])
glu_ts = df_ts[df_ts["glucose"].notna()].copy()
glu_ts = glu_ts.sort_values("ts")

if len(glu_ts) > 1:
    gaps = glu_ts["ts"].diff().dt.total_seconds().dropna()
    zero_gaps = int((gaps == 0).sum())
    print(f"  Zero-second gaps : {zero_gaps}")
    print(f"  Median gap (s)   : {gaps.median():.0f}")
    print(f"  Max gap (s)      : {gaps.max():.0f}")
else:
    zero_gaps = 0
    print("  Not enough glucose rows to test gaps")

t5_pass = zero_gaps == 0
verdict5 = "PASS" if t5_pass else "FAIL"
print(f"RESULT: {verdict5}")
results["T5_Timestamps"] = verdict5
print()

# ====================================================================
# SUMMARY
# ====================================================================
print("=" * 56)
print("  EMPIRICAL VALIDATION SUMMARY")
print("=" * 56)
for name, v in results.items():
    icon = "[+]" if v == "PASS" else "[-]"
    print(f"  {icon} {name}: {v}")

all_pass = all(v == "PASS" for v in results.values())
final = "ALL PASS" if all_pass else "SOME FAILURES"
print(f"\n  OVERALL: {final}")
print("=" * 56)
