import csv, sys
from collections import Counter

CSV = r"g:\My Drive\Scripts\Temp\TXCEAllTickets.csv"

formats = Counter()
issue_types = Counter()
projects_none = 0
with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        for col in ("Created","Updated","Resolved"):
            v = (r.get(col) or "").strip()
            if v:
                formats[col + " :: " + v] = 1  # unique values
        it = (r.get("Issue Type") or "").strip()
        if it:
            issue_types[it] += 1
        # any per-row column name warning?

print("ISSUE TYPES:", dict(issue_types))
print("UNIQUE (Created/Updated/Resolved) value samples:")
for k in list(formats)[:20]:
    print("  ", k)
