import os, runpy
os.environ['TEST_PROJECTS'] = '1'
print('TEST_PROJECTS set to', os.environ['TEST_PROJECTS'])
try:
    runpy.run_module('InitialSync.jira_tickets_initialsync.main', run_name='__main__')
except SystemExit as e:
    print('Exited with', e)
except Exception as e:
    import traceback
    traceback.print_exc()
    raise
