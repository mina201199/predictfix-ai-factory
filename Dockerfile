FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
COPY docs/manuals docs/manuals
COPY artifacts artifacts
# 前端檔案用萬用字元複製，避免與 backend/app.py 的 STATIC 清單分兩處維護而漏檔
COPY *.html *.js *.css demo-measurements.csv ./
RUN mkdir -p data
RUN useradd --uid 10001 --create-home appuser && chown -R appuser:appuser /app
USER appuser
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
