import csv, io, sys

CSV = r"g:\My Drive\Scripts\Temp\TXCEAllFields.csv"
with io.open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    first_line = f.readline()
print("header chars:", len(first_line))
# parse header with csv
cols = next(csv.reader([first_line]))
print("column count:", len(cols))
with io.open(r"g:\My Drive\Scripts\Temp\ipce_backfill\_headers.txt", "w", encoding="utf-8") as out:
    for i, c in enumerate(cols, 1):
        out.write(f"{i}\t{c}\n")
# show first 90 and count duplicates
from collections import Counter
cnt = Counter(c for c in cols if c.strip())
dups = {k: v for k, v in cnt.items() if v > 1}
print("\ntotal unique:", len(cnt), "duplicated names:", len(dups))
print("top dup counts:", sorted(dups.items(), key=lambda x: -x[1])[:15])