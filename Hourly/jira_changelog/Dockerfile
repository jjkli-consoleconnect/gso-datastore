FROM python:3.11

WORKDIR /app

COPY Hourly/jira_changelog/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY Hourly/jira_changelog . 
COPY shared /app/shared

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
