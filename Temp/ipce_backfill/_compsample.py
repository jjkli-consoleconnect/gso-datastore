import csv
CSV = r"g:\My Drive\Scripts\Temp\TXCEAllTickets.csv"
shown = 0
with open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        comp = (r.get("Components") or "").strip()
        labels = [ (r.get(c) or "").strip() for c in r.keys() if (r.get(c) or "").strip() ]
        if comp or labels:
            print("KEY", r.get("Issue key"), "| Components=", repr(comp), "| Labels=", labels[:6])
            shown += 1
        if shown >= 10:
            break