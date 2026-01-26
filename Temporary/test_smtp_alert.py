#!/usr/bin/env python3
import subprocess, smtplib, ssl, sys

def get_secret(name):
    proc = subprocess.run(["gcloud","secrets","versions","access","latest","--secret="+name], capture_output=True, text=True)
    if proc.returncode != 0:
        print("GET_SECRET_ERROR", name, proc.stderr)
        sys.exit(2)
    # strip BOM and whitespace
    return proc.stdout.strip().lstrip('\ufeff')

try:
    sender = get_secret("jira-sync-alert-email")
    password = get_secret("jira-sync-alert-password")
    recipient = get_secret("jira-sync-alert-recipient")
    subject = "Test alert from jira-sync (automated)"
    body = "This is a test alert to validate SMTP send_error_email() — ignore."
    message = f"Subject: {subject}\n\n{body}"
    context = ssl.create_default_context()
    with smtplib.SMTP('smtp.gmail.com', 587, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(sender, password)
        server.sendmail(sender, [recipient], message)
    print('EMAIL_SENT')
except Exception as e:
    print('EMAIL_ERROR', str(e))
    sys.exit(2)
