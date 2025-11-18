FROM python:3.11

WORKDIR /app

# Copy requirements from local folder
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy this subfolder into the image
COPY . .

# JQL is present in this folder
COPY JQL.txt /app/JQL.txt
COPY entrypoint.sh /app/entrypoint.sh
# Copy BigQuery credentials (from shared folder)
COPY ../shared/credentials.json /app/credentials.json

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["sh", "/app/jira_tickets_initialsync/entrypoint.sh"]