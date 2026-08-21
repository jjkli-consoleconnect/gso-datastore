import os, time
time.sleep(15)
D = r"g:\My Drive\Scripts\Temp\ipce_backfill"
for name in ["txce_allfields.log", "txce_allfields.out", "txce_allfields.err"]:
    p = os.path.join(D, name)
    print(f"=== {name} ===")
    if os.path.exists(p):
        txt = open(p, encoding="utf-8", errors="replace").read()
        print(txt[-1500:] if len(txt) > 1500 else txt)
    else:
        print("(missing)")
jp = os.path.join(D, "txce_allfields.jsonl")
if os.path.exists(jp):
    print(f"=== jsonl size MB: {round(os.path.getsize(jp)/1048576,2)} ===")
else:
    print("=== jsonl not yet ===")
    p = os.path.join(D, name)
    print(f"=== {name} ===")
    if os.path.exists(p):
        txt = open(p, encoding="utf-8", errors="replace").read()
        print(txt[-1500:] if len(txt) > 1500 else txt)
    else:
        print("(missing)")
jp = os.path.join(D, "txce_allfields.jsonl")
if os.path.exists(jp):
    print(f"=== jsonl size MB: {round(os.path.getsize(jp)/1048576,2)} ===")
else:
    print("=== jsonl not yet ===")


