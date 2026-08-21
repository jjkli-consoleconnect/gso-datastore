import csv, io, collections
CSV = r"g:\My Drive\Scripts\Temp\TXCEAllFields.csv"
idx = {}
with io.open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    rd = csv.reader(f)
    headers = next(rd)
    for i, h in enumerate(headers):
        idx.setdefault(h, i)
    want = ["Issue key","Created","Updated","Resolved","Due date","Time Spent",
            "Components","Priority","Resolution","Status","Issue Type"]
    pos = {n: idx[n] for n in want if n in idx}
    fmt = collections.Counter()
    non_empty = collections.Counter()
    total = 0
    sample = []
    for row in rd:
        total += 1
        if total > 2000:
            break
        c = row[pos["Created"]] if pos["Created"] < len(row) else ""
        if c:
            if "/" in c: fmt["slash_AMPM"] += 1
            elif "T" in c and (c.endswith("+0800") or c.endswith("+08:00")): fmt["iso_tz"] += 1
            elif "T" in c: fmt["iso_no_tz"] += 1
            else: fmt["other"] += 1
        for n in want:
            v = row[pos[n]] if pos[n] < len(row) else ""
            if v.strip(): non_empty[n] += 1
        if total <= 3:
            sample.append((row[pos["Issue key"]], c, row[pos["Updated"]],
                           row[pos["Due date"]], row[pos["Time Spent"]], row[pos["Components"]],
                           row[pos["Resolution"]]))
    print("SAMPLE ROWS", total)
    print("Created format buckets:", dict(fmt))
    print("non_empty counts:", dict(non_empty))
    for s in sample:
        print(s)

