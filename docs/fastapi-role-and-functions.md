# FastAPI 的角色和作用

本文檔詳細說明 FastAPI 在高效能日誌收集系統中的核心角色與功能。

## 🎯 FastAPI 的核心角色

### 1. **高效能 API 服務層** (app/main.py)

FastAPI 作為整個系統的前端 API 服務，負責:

- 接收來自設備的日誌請求 (POST /api/log)
- 處理批量日誌 (POST /api/logs/batch)
- 提供日誌查詢服務 (GET /api/logs/{device_id})
- 系統統計資料 (GET /api/stats)
- 健康檢查 (GET /health)
- Prometheus 監控指標 (GET /metrics)

### 2. **非同步處理引擎**

```python
# main.py:11-15
from fastapi import FastAPI, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
```

**特點:**
- 使用 `async/await` 非阻塞 I/O 模式
- 搭配 AsyncSession 進行異步資料庫操作
- 支援高並發請求處理 (~23,895 logs/sec)

### 3. **快速回應機制** (app/main.py:186-243)

```python
@app.post("/api/log", response_model=LogEntryResponse)
async def create_log(log: LogEntryRequest):
    # 1. 驗證資料
    # 2. 寫入 Redis Stream (非同步佇列)
    # 3. 立即返回 "queued" 狀態 (< 5ms)
```

**關鍵流程:**

```
1. 接收日誌 → 2. 寫入 Redis Stream → 3. 立即返回 → 4. (Worker 背景處理)
```

這種架構讓 FastAPI 可以:
- ✅ 快速回應客戶端 (P95: ~60ms)
- ✅ 不被資料庫寫入速度限制
- ✅ 將耗時操作交給 Worker 處理

### 4. **負載分散的接收端** (2 個實例)

```yaml
# docker-compose.yml
fastapi-1:
  command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 6
fastapi-2:
  command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 6
```

透過 Nginx 負載平衡分配請求到:
- FastAPI Instance 1 (6 workers)
- FastAPI Instance 2 (6 workers)
- **總計 12 個 worker processes**

### 5. **智能快取層** (app/main.py:320-406)

```python
@app.get("/api/logs/{device_id}", response_model=BatchLogQueryResponse)
async def get_logs(...):
    # 1. 先查 Redis 快取
    cached_data = await redis_client.get(cache_key)

    if cached_data:
        # Cache Hit - 直接返回
        return BatchLogQueryResponse(source="cache", ...)
    else:
        # Cache Miss - 查詢資料庫
        result = await db.execute(query)

        # 3. 寫入快取 (TTL 5分鐘)
        await redis_client.setex(cache_key, 300, json.dumps(logs_data))
```

**效益:**
- 減少資料庫負載
- 提升查詢效能
- Cache Hit 回應時間 < 10ms

### 6. **完整的監控整合** (app/metrics.py)

```python
# main.py:24-38
from metrics import (
    MetricsMiddleware,
    logs_received_total,
    redis_stream_messages_total,
    redis_cache_hits_total,
    redis_cache_misses_total,
    # ... 更多指標
)

# main.py:50
app.add_middleware(MetricsMiddleware)
```

**提供 Prometheus 格式的指標:**
- HTTP 請求統計 (QPS, 延遲, 狀態碼)
- Redis 操作時間 (XADD, GET, SET, XREADGROUP)
- 業務指標 (logs_received_total, logs_by_level)
- 系統資源監控 (CPU, Memory, Disk)

---

## 📊 架構定位

```
客戶端裝置 (100 units)
    ↓
Nginx 負載平衡器 [:18723]
    ↓
┌─────────────────────────────────┐
│ FastAPI (2 instances × 6 workers)│  ← FastAPI 在此位置
│ - 快速接收請求                   │
│ - 寫入 Redis Stream             │
│ - 立即返回 "queued"             │
│ - 查詢時使用快取                 │
└─────────────────────────────────┘
    ↓
Redis Stream (訊息佇列)
    ↓
Worker (批次處理)
    ↓
PostgreSQL (持久化儲存)
```

---

## 🔄 API 端點與功能對照表

| Method | Endpoint | 功能說明 | 檔案位置 | 回應時間 |
|--------|----------|----------|----------|----------|
| GET | `/` | 服務資訊 | main.py:496-513 | < 1ms |
| GET | `/health` | 健康檢查 (Redis + PostgreSQL) | main.py:146-182 | < 10ms |
| POST | `/api/log` | 單筆日誌寫入 | main.py:187-243 | < 5ms |
| POST | `/api/logs/batch` | 批量日誌寫入 (1-1000筆) | main.py:248-315 | < 20ms |
| GET | `/api/logs/{device_id}` | 查詢設備日誌 (含快取) | main.py:320-406 | 10-50ms |
| GET | `/api/stats` | 系統統計 (快取60秒) | main.py:411-482 | < 10ms |
| GET | `/metrics` | Prometheus 指標 | main.py:487-493 | < 5ms |
| GET | `/docs` | Swagger UI 文檔 | 自動生成 | - |
| GET | `/redoc` | ReDoc 文檔 | 自動生成 | - |

---

## 🎯 為何選擇 FastAPI？

### 1. **原生異步支援**
```python
# 支援 async/await 語法
async def create_log(log: LogEntryRequest):
    await redis_client.xadd(...)
    return response
```

### 2. **自動文檔生成**
- Swagger UI: http://localhost:18723/docs
- ReDoc: http://localhost:18723/redoc
- 無需額外維護 API 文檔

### 3. **資料驗證**
```python
# 使用 Pydantic 自動驗證
class LogEntryRequest(BaseModel):
    device_id: str = Field(..., max_length=50)
    log_level: str = Field(..., pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    message: str = Field(..., max_length=1000)
    log_data: Optional[Dict[str, Any]] = None
```

### 4. **高效能**
- 基於 Starlette 和 Pydantic
- 效能接近 Node.js 和 Go
- 實測吞吐量: ~23,895 logs/sec

### 5. **現代化開發體驗**
- 基於 Python 3.11+ 和 Type Hints
- IDE 自動補全支援
- 類型檢查 (mypy)

---

## 🚀 效能優化策略

### 1. **連線池管理**

#### Redis 連線池 (main.py:88-96)
```python
pool = redis.ConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    max_connections=200  # 支援高並發
)
redis_client = redis.Redis(connection_pool=pool)
```

#### PostgreSQL 連線池 (database.py:40-45)
```python
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=10,        # 持久連線數
    max_overflow=5,      # 額外連線數
    pool_pre_ping=True,  # 連線前檢查
    pool_recycle=3600    # 1小時回收
)
```

### 2. **批次處理 API** (main.py:248-315)

```python
@app.post("/api/logs/batch")
async def create_batch_logs(batch: BatchLogEntryRequest):
    # 使用 Redis Pipeline 批次寫入
    pipe = redis_client.pipeline()

    for log in batch.logs:
        pipe.xadd(name="logs:stream", fields=log_dict, ...)

    # 一次執行所有操作 (減少網路往返)
    results = await pipe.execute()
```

**效益:**
- 減少網路往返次數
- 提升吞吐量至 10,000+ logs/sec
- 降低平均延遲

### 3. **背景任務** (main.py:65-77)

```python
async def update_metrics_task():
    """定期更新系統指標"""
    while True:
        update_system_metrics()
        if redis_client:
            stream_len = await redis_client.xlen('logs:stream')
            redis_stream_size.set(stream_len)
        await asyncio.sleep(10)  # 每 10 秒更新
```

### 4. **中間件** (metrics.py:130-194)

```python
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()

        # 處理請求
        response = await call_next(request)

        # 記錄指標
        duration = time.time() - start_time
        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).observe(duration)

        return response
```

---

## 🔧 FastAPI 與 Worker 的分工

### FastAPI 的職責:
- ✅ **接收請求** - 驗證資料格式
- ✅ **寫入 Redis Stream** - 非同步佇列
- ✅ **立即返回** - 回應客戶端 (< 5ms)
- ✅ **查詢服務** - 使用快取加速
- ✅ **監控指標** - 收集並暴露 Prometheus metrics

### Worker 的職責 (app/worker.py):
- ✅ **消費訊息** - 從 Redis Stream 讀取
- ✅ **批次寫入** - 100 筆一批寫入 PostgreSQL
- ✅ **ACK 確認** - 確保訊息不遺失
- ✅ **錯誤重試** - 失敗自動重試

### 流程圖:

```
┌──────────┐     ┌─────────┐     ┌───────────────┐
│  Client  │────▶│ FastAPI │────▶│ Redis Stream  │
└──────────┘     └─────────┘     └───────────────┘
                      │                    │
                      │ (立即返回)          │
                      ▼                    ▼
                 200 OK              ┌─────────┐
                 {queued}            │ Worker  │
                                     └─────────┘
                                          │
                                          ▼
                                    ┌──────────┐
                                    │PostgreSQL│
                                    └──────────┘
```

---

## 📈 實際效能數據

### 壓力測試結果 (50 次迭代)

**測試環境:**
- CPU: Apple Silicon (ARM64)
- Memory: 16 GB RAM
- Storage: SSD (NVMe)
- OS: macOS

**測試配置:**
- 模擬設備: 100 台
- 每次迭代日誌數: 10,000 筆
- 並發連線: 200
- 批次大小: 5 筆/請求
- 總請求數: 100,000 (全部成功)
- 總日誌數: 500,000

**實測效能:**

| 指標 | 目標 | 實際達成 | 狀態 |
|------|------|----------|------|
| 吞吐量 | ≥ 10,000 logs/sec | ~23,895 logs/sec 平均 | ✅ 2.39x |
| P95 延遲 | ≤ 100 ms | ~60.57 ms 平均 | ✅ 達標 |
| P99 延遲 | < 500 ms | ~96.15 ms 平均 | ✅ 5.20x |
| 錯誤率 | 0% | 0% | ✅ 完美 |
| 平均回應時間 | - | 18.33 ms | ✅ 優異 |

### 效能分佈:
```
• 最快回應時間: 1.06 ms
• 最慢回應時間: 248.77 ms
• P50 (中位數): 13.54 ms
• P95: 60.57 ms (範圍: 33.93 - 107.07 ms)
• P99: 96.15 ms (範圍: 58.28 - 228.83 ms)
```

### 目標達成率:
- ✅ 吞吐量目標達成: 50/50 次迭代 (100%)
- ✅ P95 延遲目標達成: 47/50 次迭代 (94%)
- ✅ 零錯誤率: 50/50 次迭代 (100%)

---

## 🛠️ 配置參數說明

### 應用程式設定

```python
# main.py:43-47
app = FastAPI(
    title="高效能日誌收集系統",
    description="基於 FastAPI + Redis + PostgreSQL 的日誌收集系統",
    version="1.0.0"
)
```

### 實例設定

```bash
# 環境變數
INSTANCE_NAME=fastapi-1          # 實例識別名稱
REDIS_HOST=localhost             # Redis 主機
REDIS_PORT=6379                  # Redis 埠號
TZ=Asia/Taipei                   # 時區設定
```

### Worker 數量設定

```yaml
# docker-compose.yml
fastapi-1:
  command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 6
```

**建議值:**
- CPU 密集型: `workers = CPU核心數 + 1`
- I/O 密集型: `workers = (2 × CPU核心數) + 1`
- 本專案使用: 6 workers (I/O 密集型)

---

## 📚 相關文件

- [README.md](../README.md) - 專案總覽
- [app/main.py](../app/main.py) - FastAPI 主應用程式
- [app/worker.py](../app/worker.py) - 背景 Worker
- [app/models.py](../app/models.py) - 資料模型
- [app/metrics.py](../app/metrics.py) - 監控指標

---

## 📝 總結

FastAPI 在這個專案中扮演 **高吞吐量 API 閘道** 的角色:

1. ✅ **快速接收** - < 5ms 寫入 Redis Stream
2. ✅ **非同步處理** - async/await 非阻塞模式
3. ✅ **智能快取** - Redis 快取降低資料庫壓力
4. ✅ **完整監控** - Prometheus 指標整合
5. ✅ **水平擴展** - 支援多實例部署
6. ✅ **高可用性** - 健康檢查與自動重啟

**架構優勢:**
- 讀寫分離 (FastAPI 寫入 Redis, Worker 寫入 DB)
- 異步處理 (立即返回，背景處理)
- 批次優化 (減少資料庫 I/O)
- 負載平衡 (Nginx 分散流量)

這種設計讓系統能穩定處理 **~23,895 logs/second** 的高負載，同時保持低延遲 (P95 ~60ms) 與零錯誤率。
