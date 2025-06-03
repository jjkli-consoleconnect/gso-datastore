FROM python:3.9

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY credentials.json /app/credentials.json

CMD ["python", "main.py"]