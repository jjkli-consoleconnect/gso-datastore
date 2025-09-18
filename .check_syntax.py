import py_compile
files = [
    r"Hourly\jira_tickets\main.py",
    r"Hourly\jira_changelog\main.py",
    r"Hourly\jira_comments\main.py",
    r"InitialSync\jira_tickets_initialsync\main.py",
    r"InitialSync\jira_changelog_initialsync\main.py",
    r"InitialSync\jira_comments_initialsync\main.py",
]
import os, sys
root = os.path.dirname(__file__)
ok = True
for f in files:
    path = os.path.join(root, f)
    try:
        py_compile.compile(path, doraise=True)
        print(f"OK: {f}")
    except Exception as e:
        ok = False
        print(f"FAIL: {f} -> {e}")
if not ok:
    sys.exit(1)
print('All compiled successfully')
