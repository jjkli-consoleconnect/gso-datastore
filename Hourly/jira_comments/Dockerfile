FROM python:3.11

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY config.json /app/config.json
COPY credentials.json /app/credentials.json
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN ls -l /app && cat /app/config.json

ENTRYPOINT ["/app/entrypoint.sh"]
