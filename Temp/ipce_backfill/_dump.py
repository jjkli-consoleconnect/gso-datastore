import io
p = r"g:\My Drive\Scripts\Temp\ipce_backfill\backfill_creator.py"
lines = io.open(p, "r", encoding="utf-8").read().splitlines()
for i in range(78, 172):
    if i < len(lines):
        print(f"{i+1:4} | {lines[i]}")