FROM python:3.11

WORKDIR /app

# Copy requirements from the local folder so this subfolder builds independently
COPY InitialSync/jira_tickets_initialsync/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files from this subfolder into the image
COPY InitialSync/jira_tickets_initialsync/ .

# Include shared library from repo root (not InitialSync/shared)
COPY shared /app/shared

# Make entrypoint executable and use it as container entrypoint
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["sh", "/app/entrypoint.sh"]