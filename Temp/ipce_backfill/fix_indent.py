import io
p = r"g:\My Drive\Scripts\Temp\ipce_backfill\fetch_comments_changelogs.py"
s = open(p, encoding="utf-8").read()
broken = ('def main():\n'
          '    limit = None\n'
          '        if "--limit" in sys.argv:\n'
          '        limit = int(sys.argv[sys.argv.index("--limit") + 1])\n'
          '    session = build_session()\n'
          '    keys = []\n')
fixed = ('def main():\n'
         '    limit = None\n'
         '    if "--limit" in sys.argv:\n'
         '        limit = int(sys.argv[sys.argv.index("--limit") + 1])\n'
         '    session = build_session()\n'
         '    keys = []\n')
assert broken in s, "broken block not found"
s = s.replace(broken, fixed)
open(p, "w", encoding="utf-8").write(s)
print("FIXED main() indentation")
