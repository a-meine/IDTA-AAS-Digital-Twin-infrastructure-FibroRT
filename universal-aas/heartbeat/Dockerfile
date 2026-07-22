FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY heartbeat.py config.py ./
CMD ["python", "-u", "heartbeat.py"]
