FROM python:3.9

WORKDIR /app

# Copy requirements from the local folder so this subfolder builds independently
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files from this subfolder into the image
COPY . .

# JQL is present in this folder
COPY JQL.txt /app/JQL.txt
# Include shared library from repo root so imports like `shared.pipeline_runs_logger` work
COPY shared /app/shared

# Make entrypoint executable and use it as container entrypoint
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
