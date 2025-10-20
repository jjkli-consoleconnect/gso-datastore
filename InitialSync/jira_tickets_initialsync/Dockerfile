FROM python:3.9

WORKDIR /app

# Copy requirements from local folder
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy this subfolder into the image
COPY . .

# JQL is present in this folder
COPY JQL.txt /app/JQL.txt
COPY entrypoint.sh /app/entrypoint.sh
# Copy BigQuery credentials (explicitly copy the working credentials from the comments subfolder
# so the small placeholder at repo root does not overwrite it during COPY . .)
COPY jira_comments_initialsync/credentials.json /app/credentials.json
COPY service-account.json /app/service-account.json
COPY jira-bigquery-key.json /app/jira-bigquery-key.json
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["sh", "/app/jira_tickets_initialsync/entrypoint.sh"]