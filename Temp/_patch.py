import io

p = r"c:/dev/consoleconnect/Temp/create_wanda4_tickets.py"
s = io.open(p, encoding="utf-8").read()
old = 'p.split("=")[0].replace("--resume-", "").replace("-", " ").title().replace(" ", "_"): p.split("=")[1]'
new = 'p.split("=")[1]: p.split("=")[2]'
assert old in s, "old text not found"
old2 = 'if p.startswith("--resume-")'
new2 = 'if p.startswith("--resume-parent=")'
assert old2 in s
io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new).replace(old2, new2))
print("patched")
