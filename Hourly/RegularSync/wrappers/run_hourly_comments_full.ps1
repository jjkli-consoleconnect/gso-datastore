$env:GOOGLE_APPLICATION_CREDENTIALS = 'G:\My Drive\Scripts\service-account.json'
$env:LOG_LEVEL = 'DEBUG'
# No TEST_WINDOW - run full
python -u 'Hourly\jira_comments\main.py'
