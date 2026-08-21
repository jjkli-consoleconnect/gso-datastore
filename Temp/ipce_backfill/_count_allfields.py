import os, csv, time

CSV = r"g:\My Drive\Scripts\Temp\TXCEAllFields.csv"
print("size bytes:", os.path.getsize(CSV))
t0 = time.time()
n = 0
with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    headers = list(rd.fieldnames or [])
    for _ in rd:
        n += 1
print("seconds:", round(time.time() - t0, 1))
print("first 8 headers:", headers[:8])
print("row count:", n)