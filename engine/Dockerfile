FROM python:3.11-slim

WORKDIR /app/engine

COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

COPY . .

# .env and data/ are bind-mounted at runtime (see docker-compose.yml at repo root)
CMD ["python3", "-m", "ai_investing.main"]
