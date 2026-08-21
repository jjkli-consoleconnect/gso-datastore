import csv, io, sys

CSV = r"g:\My Drive\Scripts\Temp\TXCEAllFields.csv"
fields = {"Issue key","Issue Type","Status","Project name","Priority","Resolution",
          "Assignee","Reporter","Creator","Created","Updated","Resolved","Due date",
          "Time Spent","Components","Description","Environment","Feature Team","Verifier",
          "Labels","Issue id","Reporter Id","Assignee Id","Creator Id"}
rows_shown = 0
with io.open(CSV, "r", encoding="utf-8-sig", newline="") as f:
    rd = csv.DictReader(f)
    for r in rd:
        print(f"--- {r.get('Issue key')} | {r.get('Issue Type')} | {r.get('Status')} | {r.get('Project name')} | {r.get('Resolution')} | due={r.get('Due date')} | ts={r.get('Time Spent')}")
        print(f"    comp={ (r.get('Components') or '')[:80]!r}")
        print(f"    labels={[ (r.get(c) or '') for c in rd.fieldnames if c.startswith('Labels') and (r.get(c) or '').strip()][:12]}")
        rows_shown += 1
        if rows_shown >= 6:
            break
print("done", rows_shown)