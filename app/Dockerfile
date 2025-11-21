FROM python:3.11-slim

# 設定工作目錄
WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴文件
COPY requirements.txt .

# 安裝 Python 依賴
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式碼
COPY . .

# 為 Prometheus multiprocess mode 創建目錄
# 這個目錄用於在多個 worker 之間共享 metrics 數據
RUN mkdir -p /tmp/prometheus_multiproc && chmod 777 /tmp/prometheus_multiproc

# 設定 Prometheus multiprocess 環境變數
ENV prometheus_multiproc_dir=/tmp/prometheus_multiproc

# 暴露端口
EXPOSE 8000

# 預設命令（會被 docker-compose 覆蓋）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
