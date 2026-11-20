FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY planetgps_history_export.py collect.py ./
ENTRYPOINT ["python", "-u", "collect.py"]
