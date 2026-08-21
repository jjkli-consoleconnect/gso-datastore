import csv, os, sys
from collections import Counter

CSV = r"g:\My Drive\Scripts\Temp\TXCEAllFields.csv"
print("size:", os.path.getsize(CSV))
n = 0
headers = None
issue_types = Counter()
dup = Counter()
empty_key = 0
with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    headers = list(rd.fieldnames or [])
    for r in rd:
        n += 1
        k = (r.get("Issue key") or "").strip()
        if not k:
            empty_key += 1
        else:
            dup[k] += 1
        it = (r.get("Issue Type") or "").strip()
        if it:
            issue_types[it] += 1

print("=== HEADER COLUMNS (%d) ===" % len(headers))
for i, h in enumerate(headers, 1):
    print(f"  {i}: {h!r}")
print("\nrow count:", n)
print("empty key rows:", empty_key)
dups = {k: v for k, v in dup.items() if v > 1}
print("duplicate keys:", len(dups), list(dups.items())[:5])
print("issue types:", dict(issue_types))