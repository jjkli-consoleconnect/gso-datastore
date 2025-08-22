FROM python:3.9

WORKDIR /app

COPY jira_tickets_initialsync/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY jira_tickets_initialsync/. .
COPY JQL.txt /app/JQL.txt
COPY jira_tickets_initialsync/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]