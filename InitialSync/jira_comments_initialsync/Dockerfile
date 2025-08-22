FROM python:3.9

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY credentials.json /app/credentials.json
COPY ../JQL.txt /app/JQL.txt
