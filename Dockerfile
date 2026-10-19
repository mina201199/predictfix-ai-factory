FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend backend
# 建置時就載入並試跑 OCR 模型：工廠內網不能連外，執行時不得再下載任何東西
RUN python -c "from backend.nameplate import warmup; result=warmup(); print(result); assert result['ready']"
COPY docs/manuals docs/manuals
COPY artifacts artifacts
# 前端檔案用萬用字元複製，避免與 backend/app.py 的 STATIC 清單分兩處維護而漏檔
COPY *.html *.js *.css demo-measurements.csv ./
RUN mkdir -p data
RUN useradd --uid 10001 --create-home appuser && chown -R appuser:appuser /app
USER appuser
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
