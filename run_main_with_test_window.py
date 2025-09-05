import os, runpy
# Example historic window: set to a UTC hour window a few days ago
os.environ['TEST_PROJECTS']='1'
# Use an ISO format with Z or +00:00; adjust dates as needed
os.environ['TEST_WINDOW_START']='2025-08-25T00:00:00Z'
os.environ['TEST_WINDOW_END']='2025-08-25T06:00:00Z'
print('TEST_PROJECTS', os.environ['TEST_PROJECTS'])
print('TEST_WINDOW_START', os.environ['TEST_WINDOW_START'])
print('TEST_WINDOW_END', os.environ['TEST_WINDOW_END'])
runpy.run_module('InitialSync.jira_tickets_initialsync.main', run_name='__main__')
