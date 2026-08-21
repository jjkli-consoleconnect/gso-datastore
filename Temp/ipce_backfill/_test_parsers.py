import sys
sys.path.insert(0, r"g:\My Drive\Scripts\Temp\ipce_backfill")
import merge_allfields as m

print("created 22:37 ->", m.parse_dt("Aug 20, 2026 22:37"))   # expect 14:37 UTC
print("created 13:24 ->", m.parse_dt("Aug 20, 2026 13:24"))   # expect 05:24 UTC
print("due empty ->", m.parse_due(""))
print("due iso ->", m.parse_due("2026-08-20"))
print("ts 2d 3h ->", m.parse_time_spent("2d 3h"))           # expect 183600
print("ts 5h ->", m.parse_time_spent("5h"))                  # expect 18000
print("ts empty ->", m.parse_time_spent(""))
