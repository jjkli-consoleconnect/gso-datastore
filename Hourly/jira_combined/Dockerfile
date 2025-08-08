FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your script and any needed files
COPY main.py .
COPY bq_logger.py .
COPY config.json .
# If you use service account credentials for GCP, copy them too:
# COPY service-account.json .

# Set environment variable for Google credentials if needed
# ENV GOOGLE_APPLICATION_CREDENTIALS=/app/service-account.json

# Default command (can override with docker run)
CMD ["python", "main.py", "--mode", "all"]