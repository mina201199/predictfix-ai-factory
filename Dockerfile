FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY docs/manuals docs/manuals
COPY knowledge.html knowledge.js knowledge.css ./
COPY console.html console.js console.css ./
COPY workflow.html workflow.js workflow.css ./
COPY artifacts artifacts
COPY index.html factory.js factory.css live.js live.css management.js auth.js evidence.js demo-measurements.csv management.css ./
RUN mkdir -p data
RUN useradd --uid 10001 --create-home appuser && chown -R appuser:appuser /app
USER appuser
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
