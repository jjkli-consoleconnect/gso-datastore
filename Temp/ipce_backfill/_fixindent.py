import io
p = r"g:\My Drive\Scripts\Temp\ipce_backfill\merge_allfields.py"
s = io.open(p, encoding="utf-8").read()
# The editor over-indented two `return` anchors to 8 spaces; dedent them to 4.
s = s.replace("        return out_path\n", "    return out_path\n")
s = s.replace("        return int(tot) if tot else None\n", "    return int(tot) if tot else None\n")
io.open(p, "w", encoding="utf-8").write(s)
print("fixed return indentation")
