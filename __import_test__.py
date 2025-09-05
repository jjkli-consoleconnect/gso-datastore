import importlib,sys
try:
    m=importlib.import_module('InitialSync.jira_tickets_initialsync.main')
    print('IMPORT_OK')
except Exception as e:
    print('IMPORT_ERROR', type(e).__name__, e)
    sys.exit(2)
