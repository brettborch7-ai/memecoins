FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY paper_trader.py .
COPY report_metrics.py .
COPY run_all.py .

ENV PYTHONUNBUFFERED=1
CMD ["python", "run_all.py"]
