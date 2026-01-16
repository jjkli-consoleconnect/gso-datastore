FROM python:3.11

WORKDIR /app

# Copy requirements from the local folder so this subfolder builds independently
COPY InitialSync/jira_changelog_initialsync/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files from this subfolder into the image
COPY InitialSync/jira_changelog_initialsync /app/jira_changelog_initialsync

# Include shared library from repo root
COPY shared /app/shared

# Make entrypoint executable and use it as container entrypoint
RUN chmod +x /app/jira_changelog_initialsync/entrypoint.sh
ENTRYPOINT ["sh", "/app/jira_changelog_initialsync/entrypoint.sh"]
