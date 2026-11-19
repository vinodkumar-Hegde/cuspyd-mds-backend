FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY sql ./sql
ENV UPLOAD_DIR=/app/uploads PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN mkdir -p /app/uploads && useradd -r -u 10001 appuser && chown -R appuser /app/uploads
USER appuser

FROM base AS test
USER root
RUN pip install --no-cache-dir pytest ruff
COPY tests ./tests
USER appuser
CMD ["sh", "-c", "ruff check app tests --select F --no-cache && python -m pytest tests -q -p no:cacheprovider"]

FROM base AS runtime
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
