import py_compile
paths = [
    r"G:\My Drive\Scripts\Hourly\jira_tickets\main.py",
    r"G:\My Drive\Scripts\Hourly\jira_changelog\main.py",
    r"G:\My Drive\Scripts\Hourly\jira_comments\main.py",
    r"G:\My Drive\Scripts\InitialSync\jira_tickets_initialsync\main.py",
    r"G:\My Drive\Scripts\InitialSync\jira_changelog_initialsync\main.py",
    r"G:\My Drive\Scripts\InitialSync\jira_comments_initialsync\main.py",
]
for p in paths:
    try:
        py_compile.compile(p, doraise=True)
        print('OK:', p)
    except Exception as e:
        print('ERR:', p, e)
