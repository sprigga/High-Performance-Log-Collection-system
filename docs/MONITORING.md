# 日誌收集系統 - 監控架構文檔

## 目錄
1. [系統架構概覽](#系統架構概覽)
2. [監控組件說明](#監控組件說明)
3. [指標體系](#指標體系)
4. [告警機制](#告警機制)
5. [數據流程](#數據流程)
6. [部署與使用](#部署與使用)
7. [Grafana 儀表板](#grafana-儀表板)
8. [系統監控工具](#系統監控工具)
9. [最佳實踐](#最佳實踐)

---

## 系統架構概覽

監控系統基於 Prometheus + Grafana + AlertManager 的標準可觀測性架構，配合多個 Exporter 實現全方位監控。

### 核心組件

```
┌─────────────────────────────────────────────────────────────────┐
│                        監控架構圖                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐      ┌──────────────┐     ┌──────────────┐   │
│  │  FastAPI App │──────│  Prometheus  │─────│   Grafana    │   │
│  │  (2 實例)    │      │  時序資料庫  │     │  可視化面板  │   │
│  └──────────────┘      └──────────────┘     └──────────────┘   │
│         │                     │                                  │
│         │                     │                                  │
│  ┌──────┴──────┐       ┌─────┴─────┐                           │
│  │  Metrics    │       │AlertManager│                           │
│  │  Endpoint   │       │  告警管理  │                           │
│  │  /metrics   │       └───────────┘                            │
│  └─────────────┘                                                 │
│                                                                   │
│  ┌────────────────────  Exporters  ───────────────────────┐    │
│  │                                                          │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │    │
│  │  │Redis Exporter│  │Postgres Exp. │  │Node Exporter│ │    │
│  │  │  (9121)      │  │  (9187)      │  │  (9100)     │ │    │
│  │  └──────────────┘  └──────────────┘  └─────────────┘ │    │
│  │                                                          │    │
│  │  ┌──────────────┐                                       │    │
│  │  │   cAdvisor   │   容器監控                           │    │
│  │  │  (18888)     │                                       │    │
│  │  └──────────────┘                                       │    │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

### 訪問端點

| 服務 | 端口 | 用途 | 預設帳密 |
|------|------|------|----------|
| Prometheus | 9090 | 時序資料庫和查詢 | 無需認證 |
| Grafana | 3000 | 數據可視化 | admin/admin123 |
| AlertManager | 9093 | 告警管理 | 無需認證 |
| cAdvisor | 18888 | 容器監控 | 無需認證 |
| Node Exporter | 9100 | 系統資源指標 | 無需認證 |
| Redis Exporter | 9121 | Redis 指標 | 無需認證 |
| PostgreSQL Exporter | 9187 | 資料庫指標 | 無需認證 |
| FastAPI Metrics | 8000/metrics | 應用指標 | 無需認證 |

---

## 監控組件說明

### 1. Prometheus (時序資料庫)

**位置**: `monitoring/prometheus/`

**配置文件**: `prometheus.yml`

#### 主要功能
- 定期抓取各個目標的指標數據（scrape）
- 存儲時序數據（預設保留 30 天）
- 評估告警規則
- 提供 PromQL 查詢介面

#### 抓取配置

```yaml
scrape_configs:
  # FastAPI 應用程式監控 (5秒抓取一次)
  - job_name: 'fastapi'
    targets: ['log-fastapi-1:8000', 'log-fastapi-2:8000']
    metrics_path: '/metrics'
    scrape_interval: 5s

  # Redis 監控 (10秒抓取一次)
  - job_name: 'redis'
    targets: ['redis-exporter:9121']
    scrape_interval: 10s

  # PostgreSQL 監控 (10秒抓取一次)
  - job_name: 'postgres'
    targets: ['postgres-exporter:9187']
    scrape_interval: 10s

  # 系統資源監控 (10秒抓取一次)
  - job_name: 'node'
    targets: ['node-exporter:9100']
    scrape_interval: 10s

  # 容器監控 (10秒抓取一次)
  - job_name: 'cadvisor'
    targets: ['cadvisor:8080']
    scrape_interval: 10s
```

#### 關鍵配置參數

- **scrape_interval**: 15s (全局預設抓取間隔)
- **evaluation_interval**: 15s (告警規則評估間隔)
- **storage.tsdb.retention.time**: 30d (數據保留期限)
- **external_labels**: 標記叢集和環境資訊

**配置文件位置**: `monitoring/prometheus/prometheus.yml:1`

---

### 2. Grafana (可視化平台)

**位置**: `monitoring/grafana/`

#### 主要功能
- 提供直觀的數據可視化介面
- 支援多種圖表類型（折線圖、柱狀圖、儀表板等）
- 自動配置 Prometheus 資料源
- 自動載入預設儀表板

#### 目錄結構

```
monitoring/grafana/
├── provisioning/              # 自動配置目錄
│   ├── datasources/          # 資料源配置
│   │   └── prometheus.yml    # Prometheus 資料源
│   └── dashboards/           # 儀表板配置
│       └── default.yml       # 預設儀表板提供者
└── dashboards/               # 儀表板 JSON 文件
    └── log-collection-dashboard.json
```

#### 資料源配置

**位置**: `monitoring/grafana/provisioning/datasources/prometheus.yml:1`

```yaml
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    timeInterval: "15s"
```

#### 儀表板自動載入

**位置**: `monitoring/grafana/provisioning/dashboards/default.yml:1`

- 自動掃描 `/var/lib/grafana/dashboards` 目錄
- 每 10 秒更新一次
- 允許 UI 更新

---

### 3. AlertManager (告警管理)

**位置**: `monitoring/alertmanager/`

**配置文件**: `alertmanager.yml`

#### 主要功能
- 接收來自 Prometheus 的告警
- 告警分組、抑制和靜默
- 將告警路由到不同的接收器
- 支援告警去重和聚合

#### 路由配置

**位置**: `monitoring/alertmanager/alertmanager.yml:6`

```yaml
route:
  group_by: ['alertname', 'cluster', 'service']  # 按告警名稱、叢集、服務分組
  group_wait: 10s         # 等待同組其他告警的時間
  group_interval: 10s     # 發送告警批次的間隔
  repeat_interval: 12h    # 重複發送告警的間隔
  receiver: 'default'     # 預設接收器
```

#### 告警接收器

系統配置了三種接收器，都使用 Webhook 方式：

1. **default**: 一般告警 → `http://localhost:5001/alert`
2. **critical**: 嚴重告警 → `http://localhost:5001/alert/critical`
3. **warning**: 警告告警 → `http://localhost:5001/alert/warning`

**配置位置**: `monitoring/alertmanager/alertmanager.yml:24`

#### 抑制規則

**位置**: `monitoring/alertmanager/alertmanager.yml:41`

- 當有 critical 級別告警時，會抑制相同服務的 warning 告警
- 避免告警疲勞

---

### 4. Exporters (指標導出器)

#### 4.1 Redis Exporter

**映像**: `oliver006/redis_exporter:latest`

**端口**: 9121

**環境變數**: `REDIS_ADDR=redis:6379`

**提供指標**:
- Redis 連線狀態
- 鍵空間統計
- 記憶體使用
- 命令執行統計
- Stream 相關指標

**配置位置**: `docker-compose.monitoring.yml:71`

---

#### 4.2 PostgreSQL Exporter

**映像**: `prometheuscommunity/postgres-exporter:latest`

**端口**: 9187

**連線字串**: `postgresql://loguser:logpass@postgres:5432/logsdb?sslmode=disable`

**提供指標**:
- 資料庫連線數
- 查詢效能
- 資料表大小
- 索引使用情況
- 交易統計

**配置位置**: `docker-compose.monitoring.yml:87`

---

#### 4.3 Node Exporter

**映像**: `prom/node-exporter:latest`

**端口**: 9100

**掛載點**:
- `/proc:/host/proc:ro`
- `/sys:/host/sys:ro`
- `/:/rootfs:ro`

**提供指標**:
- CPU 使用率
- 記憶體使用
- 磁碟 I/O
- 網路流量
- 檔案系統狀態

**配置位置**: `docker-compose.monitoring.yml:103`

---

#### 4.4 cAdvisor (容器監控)

**映像**: `gcr.io/cadvisor/cadvisor:latest`

**端口**: 18888 (避免與其他服務衝突，原為 8080)

**特殊配置**: 需要 privileged 模式和 /dev/kmsg 裝置

**提供指標**:
- 容器 CPU 使用率
- 容器記憶體使用
- 容器網路流量
- 容器檔案系統使用
- 容器生命週期事件

**配置位置**: `docker-compose.monitoring.yml:124`

---

## 指標體系

### 指標模組架構

**位置**: `app/metrics.py:1`

系統使用 `prometheus_client` 庫實現指標收集，分為以下幾大類別：

### 1. HTTP 請求指標

#### http_requests_total (Counter)
- **描述**: HTTP 請求總數
- **標籤**: method, endpoint, status
- **用途**: 追蹤請求量和錯誤率
- **定義位置**: `app/metrics.py:15`

#### http_request_duration_seconds (Histogram)
- **描述**: HTTP 請求持續時間（秒）
- **標籤**: method, endpoint
- **分桶**: 0.001s ~ 10s（13 個分桶）
- **用途**: 分析請求延遲分佈（P50, P95, P99）
- **定義位置**: `app/metrics.py:21`

#### http_request_size_bytes / http_response_size_bytes (Summary)
- **描述**: 請求/回應大小（位元組）
- **標籤**: method, endpoint
- **用途**: 監控網路流量
- **定義位置**: `app/metrics.py:28`

---

### 2. Redis 指標

#### redis_stream_messages_total (Counter)
- **描述**: 寫入 Redis Stream 的訊息總數
- **標籤**: status (success/failed)
- **用途**: 追蹤訊息寫入成功率
- **定義位置**: `app/metrics.py:41`

#### redis_stream_size (Gauge)
- **描述**: Redis Stream 當前大小
- **用途**: 監控訊息堆積情況
- **定義位置**: `app/metrics.py:47`

#### redis_cache_hits_total / redis_cache_misses_total (Counter)
- **描述**: 快取命中/未命中次數
- **用途**: 計算快取命中率
- **定義位置**: `app/metrics.py:52`

#### redis_operation_duration_seconds (Histogram)
- **描述**: Redis 操作持續時間
- **標籤**: operation (xadd, get, set, xreadgroup)
- **分桶**: 0.0001s ~ 0.1s（9 個分桶）
- **用途**: 監控 Redis 操作效能
- **定義位置**: `app/metrics.py:62`

---

### 3. 資料庫指標

#### db_connections_active / db_connections_idle (Gauge)
- **描述**: 活躍/閒置的資料庫連線數
- **標籤**: pool (master/replica)
- **用途**: 監控連線池狀態
- **定義位置**: `app/metrics.py:70`

#### db_query_duration_seconds (Histogram)
- **描述**: 資料庫查詢持續時間
- **標籤**: query_type (select/insert/update/delete), pool
- **分桶**: 0.001s ~ 5s（11 個分桶）
- **用途**: 分析查詢效能
- **定義位置**: `app/metrics.py:82`

#### db_queries_total (Counter)
- **描述**: 資料庫查詢總數
- **標籤**: query_type, status (success/error)
- **用途**: 追蹤查詢量和錯誤率
- **定義位置**: `app/metrics.py:89`

---

### 4. 業務指標

#### logs_received_total (Counter)
- **描述**: 接收的日誌總數
- **標籤**: device_id, log_level
- **用途**: 追蹤日誌接收量
- **定義位置**: `app/metrics.py:96`

#### logs_processing_errors_total (Counter)
- **描述**: 日誌處理錯誤總數
- **標籤**: error_type
- **用途**: 監控處理錯誤
- **定義位置**: `app/metrics.py:102`

#### batch_processing_duration_seconds (Histogram)
- **描述**: 批次處理持續時間
- **標籤**: batch_size
- **分桶**: 0.01s ~ 10s（8 個分桶）
- **用途**: 優化批次大小
- **定義位置**: `app/metrics.py:108`

#### active_devices_total (Gauge)
- **描述**: 活躍設備總數
- **用途**: 監控設備連線狀態
- **定義位置**: `app/metrics.py:115`

---

### 5. 系統資源指標

#### system_cpu_usage_percent (Gauge)
- **描述**: 系統 CPU 使用率百分比
- **用途**: 監控 CPU 負載
- **定義位置**: `app/metrics.py:121`
- **更新函數**: `app/metrics.py:197`

#### system_memory_usage_bytes (Gauge)
- **描述**: 系統記憶體使用量（位元組）
- **標籤**: type (used/available/total)
- **用途**: 監控記憶體使用
- **定義位置**: `app/metrics.py:126`
- **更新函數**: `app/metrics.py:203`

#### system_disk_usage_bytes (Gauge)
- **描述**: 系統磁碟使用量（位元組）
- **標籤**: type (used/free/total)
- **用途**: 監控磁碟空間
- **定義位置**: `app/metrics.py:132`
- **更新函數**: `app/metrics.py:209`

---

### 6. Worker 指標

#### worker_active_tasks (Gauge)
- **描述**: 活躍的 Worker 任務數
- **標籤**: worker_id
- **用途**: 監控 Worker 負載
- **定義位置**: `app/metrics.py:139`

#### worker_processed_logs_total (Counter)
- **描述**: Worker 處理的日誌總數
- **標籤**: worker_id, status (success/failed)
- **用途**: 追蹤 Worker 處理量
- **定義位置**: `app/metrics.py:145`

#### worker_batch_size (Histogram)
- **描述**: Worker 批次大小分佈
- **分桶**: 10 ~ 1000（7 個分桶）
- **用途**: 優化批次處理
- **定義位置**: `app/metrics.py:151`

---

### 指標收集機制

#### 1. MetricsMiddleware (自動收集 HTTP 指標)

**位置**: `app/metrics.py:216`

**功能**:
- 自動攔截所有 HTTP 請求
- 記錄請求時間、大小、狀態碼
- 記錄回應大小
- 簡化路徑避免高基數問題

**路徑簡化邏輯** (`app/metrics.py:285`):
- 將動態參數（如設備 ID）替換為 `{param}`
- 避免 Prometheus 標籤爆炸

**範例**:
```
/api/logs/device123/status → /api/logs/{param}/status
```

#### 2. track_time 裝飾器

**位置**: `app/metrics.py:159`

**功能**:
- 追蹤函數執行時間
- 支援同步和非同步函數
- 可傳入自訂標籤

**使用範例**:
```python
@track_time(redis_operation_duration_seconds, {'operation': 'xadd'})
async def write_to_stream(data):
    # ... 寫入邏輯
```

#### 3. update_system_metrics 函數

**位置**: `app/metrics.py:197`

**功能**:
- 使用 psutil 收集系統資源指標
- 定期更新 CPU、記憶體、磁碟使用量

---

## 告警機制

### 告警規則配置

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:1`

系統定義了 7 種告警規則，分為 warning 和 critical 兩個級別。

---

### 1. HighAPILatency (API 回應時間過高)

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:7`

**級別**: warning

**條件**: P95 回應時間 > 500ms

**持續時間**: 5 分鐘

**PromQL 表達式**:
```promql
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.5
```

**觸發場景**:
- 資料庫查詢變慢
- Redis 操作延遲
- 系統資源不足

---

### 2. HighErrorRate (錯誤率過高)

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:17`

**級別**: critical

**條件**: 5xx 錯誤率 > 5%

**持續時間**: 5 分鐘

**PromQL 表達式**:
```promql
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
```

**觸發場景**:
- 應用程式異常
- 資料庫連線失敗
- Redis 連線問題

---

### 3. RedisStreamBacklog (Redis Stream 訊息堆積)

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:27`

**級別**: warning

**條件**: Stream 大小 > 50,000

**持續時間**: 10 分鐘

**PromQL 表達式**:
```promql
redis_stream_size > 50000
```

**觸發場景**:
- Worker 處理速度跟不上
- Worker 服務停機
- 突發大量日誌

---

### 4. HighCPUUsage (系統 CPU 使用率過高)

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:37`

**級別**: warning

**條件**: CPU 使用率 > 80%

**持續時間**: 10 分鐘

**PromQL 表達式**:
```promql
system_cpu_usage_percent > 80
```

**觸發場景**:
- 請求量暴增
- 資源密集型運算
- 無限迴圈或效能問題

---

### 5. HighMemoryUsage (系統記憶體使用率過高)

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:47`

**級別**: warning

**條件**: 記憶體使用率 > 85%

**持續時間**: 10 分鐘

**PromQL 表達式**:
```promql
(system_memory_usage_bytes{type='used'} / system_memory_usage_bytes{type='total'}) * 100 > 85
```

**觸發場景**:
- 記憶體洩漏
- 快取過大
- 批次處理數據量過大

---

### 6. ServiceDown (服務停機)

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:57`

**級別**: critical

**條件**: 服務無法連線

**持續時間**: 1 分鐘

**PromQL 表達式**:
```promql
up{job=~"fastapi|redis|postgres"} == 0
```

**觸發場景**:
- 容器崩潰
- 網路問題
- 服務配置錯誤

---

### 7. LowCacheHitRate (Redis 快取命中率過低)

**位置**: `monitoring/prometheus/alerts/app_alerts.yml:67`

**級別**: warning

**條件**: 快取命中率 < 50%

**持續時間**: 15 分鐘

**PromQL 表達式**:
```promql
rate(redis_cache_hits_total[5m]) / (rate(redis_cache_hits_total[5m]) + rate(redis_cache_misses_total[5m])) < 0.5
```

**觸發場景**:
- 快取策略不當
- 快取過期時間太短
- 存取模式變化

---

## 數據流程

### 指標收集流程

```
┌──────────────────────────────────────────────────────────────┐
│                        指標收集流程                            │
└──────────────────────────────────────────────────────────────┘

1. 應用層指標生成
   ┌─────────────┐
   │ FastAPI App │
   └──────┬──────┘
          │
          ├─► MetricsMiddleware → HTTP 指標
          ├─► track_time 裝飾器 → 函數執行時間
          └─► update_system_metrics() → 系統資源指標

2. Exporter 指標生成
   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
   │ Redis        │    │ PostgreSQL   │    │ Node/cAdvisor│
   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
          │                   │                    │
   ┌──────▼───────┐    ┌─────▼────────┐    ┌─────▼────────┐
   │Redis Exporter│    │Postgres Exp. │    │ System Metrics│
   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
          │                   │                    │
          └───────────────────┴────────────────────┘
                              │
3. Prometheus 抓取           │
   ┌────────────────────────▼─┐
   │      Prometheus          │
   │  每 5-15 秒抓取一次指標   │
   └────────────┬──────────────┘
                │
4. 資料儲存與查詢           │
                ├─► 時序資料庫 (30 天保留)
                ├─► 告警規則評估 (每 15 秒)
                └─► PromQL 查詢介面

5. 可視化與告警
   ┌──────────┐         ┌──────────────┐
   │ Grafana  │         │ AlertManager │
   │ 儀表板   │         │  告警路由    │
   └──────────┘         └──────────────┘
```

---

### 告警處理流程

```
1. 告警觸發
   ┌──────────────┐
   │ Prometheus   │  評估告警規則 (每 15s)
   └──────┬───────┘
          │
          ▼
   條件滿足且持續指定時間？
          │
          ▼ Yes

2. 發送至 AlertManager
   ┌──────────────┐
   │AlertManager  │
   └──────┬───────┘
          │
          ├─► 分組 (group_by)
          ├─► 抑制 (inhibit_rules)
          └─► 路由 (route)

3. 路由決策
          │
          ├─► severity: critical  → critical receiver
          │                        → http://localhost:5001/alert/critical
          │
          ├─► severity: warning   → warning receiver
          │                        → http://localhost:5001/alert/warning
          │
          └─► default             → default receiver
                                   → http://localhost:5001/alert

4. Webhook 通知
   外部告警處理系統接收通知並執行相應動作
```

---

## 部署與使用

### 啟動監控系統

使用提供的啟動腳本：

```bash
# 執行啟動腳本
./monitoring/start_monitoring.sh
```

**腳本功能** (`monitoring/start_monitoring.sh:1`):
1. 檢查 Docker 是否運行
2. 同時啟動應用服務和監控服務
3. 等待服務啟動（10 秒）
4. 顯示服務狀態和訪問 URL

**實際執行的命令**:
```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

---

### 停止監控系統

```bash
# 執行停止腳本
./monitoring/stop_monitoring.sh
```

**腳本功能** (`monitoring/stop_monitoring.sh:1`):
```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down
```

---

### 手動部署

#### 1. 僅啟動監控服務

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

#### 2. 查看服務狀態

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml ps
```

#### 3. 查看服務日誌

```bash
# 查看所有監控服務日誌
docker compose -f docker-compose.monitoring.yml logs -f

# 查看特定服務日誌
docker compose -f docker-compose.monitoring.yml logs -f prometheus
docker compose -f docker-compose.monitoring.yml logs -f grafana
```

#### 4. 重啟特定服務

```bash
docker compose -f docker-compose.monitoring.yml restart prometheus
docker compose -f docker-compose.monitoring.yml restart grafana
```

---

### 配置修改

#### 修改 Prometheus 配置

```bash
# 1. 編輯配置文件
vim monitoring/prometheus/prometheus.yml

# 2. 重新載入配置（不停機）
docker exec log-prometheus kill -HUP 1

# 或者重啟服務
docker compose -f docker-compose.monitoring.yml restart prometheus
```

#### 修改告警規則

```bash
# 1. 編輯告警規則
vim monitoring/prometheus/alerts/app_alerts.yml

# 2. 重新載入配置
docker exec log-prometheus kill -HUP 1
```

#### 修改 Grafana Dashboard

```bash
# 1. 編輯儀表板 JSON
vim monitoring/grafana/dashboards/log-collection-dashboard.json

# 2. Grafana 會在 10 秒內自動重新載入
```

---

## Grafana 儀表板

### 儀表板概覽

**名稱**: 日誌收集系統效能儀表板

**UID**: `log-collection-system`

**刷新頻率**: 10 秒

**時間範圍**: 最近 1 小時

**配置文件**: `monitoring/grafana/dashboards/log-collection-dashboard.json:1`

---

### 面板說明

#### Panel 1: 每秒請求數 (QPS)
**位置**: 第 1 列左側

**查詢**:
- 總 QPS: `sum(rate(http_requests_total[1m]))`
- 成功請求: `sum(rate(http_requests_total{status=~"2.."}[1m]))`
- 錯誤請求: `sum(rate(http_requests_total{status=~"5.."}[1m]))`

**用途**: 監控系統整體請求量和成功率

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:13`

---

#### Panel 2: HTTP 請求延遲 (P50, P95, P99)
**位置**: 第 1 列右側

**查詢**:
- P50: `histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`
- P95: `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`
- P99: `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`

**用途**: 分析請求延遲分佈

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:47`

---

#### Panel 3: Redis Stream 大小
**位置**: 第 2 列左側

**查詢**: `redis_stream_size`

**用途**: 監控訊息隊列堆積

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:81`

---

#### Panel 4: Redis 快取命中率
**位置**: 第 2 列中間

**查詢**:
```promql
rate(redis_cache_hits_total[5m]) /
(rate(redis_cache_hits_total[5m]) + rate(redis_cache_misses_total[5m])) * 100
```

**用途**: 評估快取效能

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:106`

---

#### Panel 5: Redis 操作延遲
**位置**: 第 2 列右側

**查詢**:
```promql
histogram_quantile(0.95, sum(rate(redis_operation_duration_seconds_bucket[5m])) by (le, operation))
```

**用途**: 分析各種 Redis 操作的 P95 延遲

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:131`

---

#### Panel 6: 系統 CPU 使用率
**位置**: 第 3 列左側

**查詢**: `system_cpu_usage_percent`

**用途**: 監控系統 CPU 負載

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:155`

---

#### Panel 7: 系統記憶體使用
**位置**: 第 3 列中間

**查詢**:
- 已使用: `system_memory_usage_bytes{type='used'}`
- 可用: `system_memory_usage_bytes{type='available'}`

**用途**: 監控記憶體使用情況

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:181`

---

#### Panel 8: 每秒日誌接收數
**位置**: 第 3 列右側

**查詢**: `sum(rate(logs_received_total[1m])) by (log_level)`

**用途**: 按日誌級別統計接收量

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:210`

---

#### Panel 9: Redis Stream 寫入狀態
**位置**: 第 4 列左側

**查詢**:
- 成功: `rate(redis_stream_messages_total{status='success'}[1m])`
- 失敗: `rate(redis_stream_messages_total{status='failed'}[1m])`

**用途**: 監控訊息寫入成功率

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:233`

---

#### Panel 10: 系統磁碟使用
**位置**: 第 4 列右側

**查詢**:
- 已使用: `system_disk_usage_bytes{type='used'}`
- 可用: `system_disk_usage_bytes{type='free'}`

**用途**: 監控磁碟空間

**配置位置**: `monitoring/grafana/dashboards/log-collection-dashboard.json:263`

---

## 系統監控工具

### system_monitor.py

**位置**: `monitoring/system_monitor.py:1`

這是一個獨立的 Python 監控工具，提供即時系統資源監控和健康檢查。

#### 主要功能

1. **系統資訊收集** (`monitoring/system_monitor.py:13`)
   - CPU 使用率（總體和每核心）
   - 記憶體使用
   - 磁碟使用
   - 網路 I/O 統計

2. **Docker 容器監控** (`monitoring/system_monitor.py:84`)
   - 容器 CPU 使用率
   - 容器記憶體使用
   - 網路和區塊 I/O

3. **系統健康檢查** (`monitoring/system_monitor.py:142`)
   - CPU > 90%: 嚴重問題
   - CPU > 70%: 警告
   - 記憶體 > 90%: 嚴重問題
   - 記憶體 > 80%: 警告
   - 磁碟 > 90%: 嚴重問題
   - 磁碟 > 80%: 警告

#### 使用方式

##### 1. 單次查看系統資訊

```bash
python3 monitoring/system_monitor.py -s
```

##### 2. 持續監控（預設 5 秒更新）

```bash
python3 monitoring/system_monitor.py
```

##### 3. 自訂更新間隔

```bash
python3 monitoring/system_monitor.py -i 10  # 每 10 秒更新
```

##### 4. 包含 Docker 監控

```bash
python3 monitoring/system_monitor.py -d
```

##### 5. 輸出到文件

```bash
python3 monitoring/system_monitor.py -o /tmp/system_metrics.jsonl
```

##### 6. 健康檢查

```bash
python3 monitoring/system_monitor.py -c

# 返回值:
# 0 = 健康
# 1 = 有問題
```

#### 命令列參數

| 參數 | 說明 | 預設值 |
|------|------|--------|
| `-i, --interval` | 更新間隔（秒） | 5 |
| `-o, --output` | 輸出文件路徑 | 無 |
| `-d, --docker` | 包含 Docker 監控 | False |
| `-c, --check` | 執行健康檢查後退出 | False |
| `-s, --single` | 只顯示一次後退出 | False |

**參數定義位置**: `monitoring/system_monitor.py:188`

---

## 最佳實踐

### 1. 監控指標設計

#### 避免高基數標籤
❌ **錯誤**:
```python
http_requests_total.labels(
    endpoint=f"/api/device/{device_id}/logs"  # device_id 有數千個
)
```

✅ **正確**:
```python
http_requests_total.labels(
    endpoint="/api/device/{param}/logs"  # 使用佔位符
)
```

**實作位置**: `app/metrics.py:285`

---

#### 選擇合適的指標類型

- **Counter**: 只增不減的計數（請求數、錯誤數）
- **Gauge**: 可增可減的數值（記憶體使用、連線數）
- **Histogram**: 觀察值分佈（延遲、大小）
- **Summary**: 類似 Histogram，但在客戶端計算分位數

---

### 2. 告警規則設計

#### 設定合理的閾值

基於實際業務需求和系統容量設定：
- API 延遲: P95 < 500ms
- 錯誤率: < 5%
- CPU 使用: < 80%
- 記憶體使用: < 85%

#### 使用適當的持續時間

避免短暫波動觸發告警：
- 嚴重問題: 1-5 分鐘
- 一般警告: 5-15 分鐘

**範例** (`monitoring/prometheus/alerts/app_alerts.yml:9`):
```yaml
for: 5m  # 必須持續 5 分鐘才觸發
```

---

### 3. Grafana 儀表板設計

#### 合理的刷新頻率

- 生產監控: 10-30 秒
- 開發調試: 5 秒
- 歷史分析: 不需要刷新

**配置** (`monitoring/grafana/dashboards/log-collection-dashboard.json:7`):
```json
"refresh": "10s"
```

#### 使用適當的時間範圍

- 即時監控: 最近 1 小時
- 趨勢分析: 最近 24 小時
- 容量規劃: 最近 30 天

---

### 4. 資源優化

#### Prometheus 資料保留

預設 30 天，根據磁碟容量調整：

```yaml
# monitoring/prometheus/prometheus.yml
command:
  - '--storage.tsdb.retention.time=30d'
```

**配置位置**: `docker-compose.monitoring.yml:21`

#### 抓取間隔優化

- 高頻指標（FastAPI）: 5 秒
- 一般指標（Redis、PostgreSQL）: 10 秒
- 低頻指標（系統資源）: 15 秒

---

### 5. 安全性考量

#### 修改預設密碼

```yaml
# docker-compose.monitoring.yml
environment:
  - GF_SECURITY_ADMIN_PASSWORD=admin123  # ⚠️ 生產環境請更改
```

**配置位置**: `docker-compose.monitoring.yml:38`

#### 網路隔離

所有監控服務使用 `log-network` 內部網路，僅暴露必要端口。

#### 敏感資料保護

避免在指標標籤中包含：
- 用戶 ID
- 密碼
- Token
- 個人資訊

---

### 6. 效能調優

#### MetricsMiddleware 優化

**路徑簡化** (`app/metrics.py:301`):
- 限制已知端點列表
- 動態參數檢測（包含數字、長度 > 10）

#### 批次處理指標

避免每次操作都更新指標，使用批次更新：

```python
# ❌ 每次都更新
for log in logs:
    logs_received_total.labels(device_id=log.device_id).inc()

# ✅ 批次更新
from collections import Counter
counts = Counter(log.device_id for log in logs)
for device_id, count in counts.items():
    logs_received_total.labels(device_id=device_id).inc(count)
```

---

### 7. 故障排查

#### 檢查 Prometheus Targets

訪問 `http://localhost:9090/targets` 查看所有抓取目標狀態。

#### 檢查告警狀態

訪問 `http://localhost:9090/alerts` 查看告警規則狀態。

#### 檢查 AlertManager

訪問 `http://localhost:9093` 查看告警分組和靜默規則。

#### 查看容器日誌

```bash
# 查看 Prometheus 日誌
docker logs log-prometheus

# 查看 Grafana 日誌
docker logs log-grafana

# 查看 AlertManager 日誌
docker logs log-alertmanager
```

---

## 總結

本監控系統提供了完整的可觀測性解決方案，包括：

1. **多維度指標收集**: HTTP、Redis、PostgreSQL、系統資源、業務指標
2. **靈活的告警機制**: 7 種預設告警規則，支援分級路由
3. **直觀的可視化**: 10 個監控面板，涵蓋系統各個層面
4. **自動化部署**: 一鍵啟動/停止腳本
5. **獨立監控工具**: Python 腳本支援健康檢查和即時監控

### 架構優勢

- ✅ **完全容器化**: 所有組件使用 Docker 部署
- ✅ **高可用性**: 支援多實例監控
- ✅ **低侵入性**: MetricsMiddleware 自動收集指標
- ✅ **可擴展性**: 易於添加新的指標和告警規則
- ✅ **標準化**: 使用業界標準工具（Prometheus、Grafana）

### 後續優化方向

1. 整合告警通知（Email、Slack、釘釘）
2. 添加日誌聚合系統（ELK/Loki）
3. 實現分散式追蹤（Jaeger/Zipkin）
4. 優化長期儲存（Thanos/VictoriaMetrics）
5. 增加自動擴縮容機制

---

## 如何使用監控及量測工具

### 監控架構概述

日誌收集系統使用分層監控架構：

```
┌─────────────────────────────────────────────────────────────┐
│                   監控架構圖                                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐     ┌────────────────┐    ┌─────────────┐ │
│  │ FastAPI App │─────│ Redis Exporter │────│ Prometheus  │ │
│  │ (metrics)   │     │  (9121)        │    │ (9090)      │ │
│  └─────────────┘     └────────────────┘    └─────────────┘ │
│         │                                           │       │
│         │                                           │       │
│  ┌──────▼─────────────┐                             │       │
│  │ PostgreSQL Exporter│                             │       │
│  │ (9187)             │                             │       │
│  └────────────────────┘                             │       │
│         │                                           │       │
│         └───────────────────────────────────────────▼───────┤
│                                                             │
│  ┌────────────────────┐    ┌──────────────────────────────┐ │
│  │ Grafana            │    │ AlertManager               │ │
│  │ (3000)             │    │ (9093)                     │ │
│  └────────────────────┘    └──────────────────────────────┘ │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 監控工具使用方式

#### 1. FastAPI 應用指標收集

應用程式使用 `prometheus_client` 庫收集指標，主要分為以下類別：

- **HTTP 請求指標**：自動透過 `MetricsMiddleware` 收集
- **Redis 指標**：手動在 Redis 操作時記錄
- **資料庫指標**：目前定義但未完全實現，未來可擴展
- **系統資源指標**：透過 `psutil` 定期收集
- **業務指標**：日誌接收、處理錯誤等

#### 2. Redis 指標收集與存取

Redis 指標主要透過兩種方式收集：

**方式一：應用層面指標**
- `redis_stream_messages_total`: 記錄寫入 Redis Stream 的訊息總數
- `redis_stream_size`: 追蹤 Redis Stream 當前大小
- `redis_cache_hits_total` / `redis_cache_misses_total`: 快取命中/未命中計數
- `redis_operation_duration_seconds`: 記錄 Redis 操作延遲（xadd, get, set, xreadgroup）

**方式二：Redis Exporter**
- 配置於 `docker-compose.monitoring.yml:71`
- 連接 `redis:6379` 服務
- 提供原生 Redis 指標如連線狀態、記憶體使用、鍵空間等

#### 3. PostgreSQL 指標收集與存取

PostgreSQL 指標也透過兩種方式收集：

**方式一：應用層面指標**
- `db_connections_active` / `db_connections_idle`: 連線池狀態
- `db_query_duration_seconds`: 查詢延遲分佈
- `db_queries_total`: 查詢總數

**注意**: 目前應用程式代碼中已定義這些指標變量，但尚未在實際的資料庫查詢函數中記錄指標。
在未來的實現中，可在 `main.py` 的查詢函數中加入類似以下的代碼：
```python
# 追蹤資料庫查詢時間和結果
start_time = time.time()
try:
    result = await db.execute(query)
    duration = time.time() - start_time
    db_query_duration_seconds.labels(query_type='select', pool='master').observe(duration)
    db_queries_total.labels(query_type='select', status='success').inc()
    return result
except Exception as e:
    duration = time.time() - start_time
    db_query_duration_seconds.labels(query_type='select', pool='master').observe(duration)
    db_queries_total.labels(query_type='select', status='error').inc()
    raise
```

**方式二：PostgreSQL Exporter**
- 配置於 `docker-compose.monitoring.yml:87`
- 連接 `postgres:5432` 服務
- 提供原生 PostgreSQL 指標如查詢效能、連線數、交易統計等

#### 4. 指標存取端點

- **應用指標**: `http://localhost:18723/metrics` 或 `http://<fastapi-host>:8000/metrics`
- **Redis Exporter**: `http://localhost:9121/metrics`
- **PostgreSQL Exporter**: `http://localhost:9187/metrics`
- **Prometheus**: `http://localhost:9090`
- **Grafana**: `http://localhost:3000`

#### 5. 自定義監控腳本

`monitoring/system_monitor.py` 提供額外的系統監控功能：

- `python3 monitoring/system_monitor.py -s`: 單次查看系統資訊
- `python3 monitoring/system_monitor.py -i 10`: 持續監控，每10秒更新
- `python3 monitoring/system_monitor.py -d`: 包含 Docker 容器監控
- `python3 monitoring/system_monitor.py -c`: 執行系統健康檢查

### 量測工具的實際應用

#### Redis 量測應用

1. **效能監控**: 透過 `redis_operation_duration_seconds` 監控 Redis 操作延遲
2. **容量規劃**: 透過 `redis_stream_size` 監控訊息堆積情況
3. **可靠性分析**: 透過 `redis_stream_messages_total` 監控寫入成功率
4. **快取效率**: 透過 `redis_cache_hits_total` 和 `redis_cache_misses_total` 計算快取命中率

#### PostgreSQL 量測應用

1. **查詢效能**: 透過 `db_query_duration_seconds` 分析查詢延遲
2. **連線池效率**: 透過 `db_connections_active` 和 `db_connections_idle` 監控連線池使用
3. **錯誤追蹤**: 透過 `db_queries_total` 監控查詢成功率

### 在代碼中擴展資料庫指標

要實現資料庫查詢的完整監控，需在 `main.py` 的資料庫查詢函數中加入以下模式：

```python
from metrics import db_query_duration_seconds, db_queries_total

async def get_logs_with_metrics(device_id: str, limit: int, db: AsyncSession):
    start_time = time.time()
    query_type = 'select'

    try:
        # 執行查詢
        query = select(Log).where(Log.device_id == device_id).order_by(Log.created_at.desc()).limit(limit)
        result = await db.execute(query)
        logs = result.scalars().all()

        # 記錄成功指標
        duration = time.time() - start_time
        db_query_duration_seconds.labels(query_type=query_type, pool='master').observe(duration)
        db_queries_total.labels(query_type=query_type, status='success').inc()

        return logs
    except Exception as e:
        # 記錄錯誤指標
        duration = time.time() - start_time
        db_query_duration_seconds.labels(query_type=query_type, pool='master').observe(duration)
        db_queries_total.labels(query_type=query_type, status='error').inc()
        raise
```

---

## 壓力測試監控指南

### 概述

本章節說明如何在執行 `tests/stress_test.py` 壓力測試時，透過 Prometheus、Grafana 和各種 Exporters 查看和分析量測數據。

### 測試前準備

#### 1. 啟動監控系統

確保監控系統已啟動：

```bash
# 使用啟動腳本（推薦）
./monitoring/start_monitoring.sh

# 或手動啟動
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

#### 2. 確認服務狀態

```bash
# 查看所有服務狀態
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml ps

# 確認監控端點可訪問
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3000/api/health  # Grafana
```

### 執行壓力測試

#### 測試配置

**位置**: `tests/stress_test.py:14-25`

測試腳本的預設配置：

```python
BASE_URL = "http://localhost:18723"  # Nginx 端點
NUM_DEVICES = 100                    # 設備數量
LOGS_PER_DEVICE = 100                # 每台設備發送的日誌數
CONCURRENT_LIMIT = 200               # 並發限制
BATCH_SIZE = 5                       # 批次大小
USE_BATCH_API = True                 # 使用批量 API
```

**總日誌數**: 100 設備 × 100 日誌 = 10,000 筆

**效能目標**:
- 吞吐量: ≥ 10,000 logs/秒
- P95 回應時間: < 100ms
- 錯誤率: 0%

#### 執行測試

```bash
# 使用 uv 切換 Python 環境執行
uv run python tests/stress_test.py
```

測試腳本會自動輸出結果摘要（`tests/stress_test.py:310-373`）：

```
📈 測試結果
⏱️  時間統計：
  • 總耗時: X 秒

📊 請求統計：
  • 批量請求數: X
  • 總日誌數: 10,000
  • 成功日誌: X (X%)

⚡ 效能指標：
  • 吞吐量: X logs/秒
  • 平均回應時間: X ms

📉 百分位數：
  • P50: X ms
  • P95: X ms
  • P99: X ms

🎯 目標達成情況：
  ✅/❌ 吞吐量達標: X >= 10,000 logs/秒
  ✅/❌ P95 回應時間達標: X <= 100 ms
```

### 在 Prometheus 查看指標

**訪問**: http://localhost:9090

#### 核心查詢表達式

##### 1. HTTP 效能指標

**每秒請求數 (QPS)**:
```promql
sum(rate(http_requests_total[1m]))
```

**成功請求率**:
```promql
sum(rate(http_requests_total{status=~"2.."}[1m])) / sum(rate(http_requests_total[1m])) * 100
```

**錯誤率**:
```promql
sum(rate(http_requests_total{status=~"5.."}[1m])) / sum(rate(http_requests_total[1m])) * 100
```

**P50/P95/P99 回應時間**:
```promql
# P50 (中位數)
histogram_quantile(0.50, rate(http_request_duration_seconds_bucket[5m]))

# P95
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# P99
histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))
```

##### 2. Redis 效能指標

**Stream 當前大小（監控訊息堆積）**:
```promql
redis_stream_size
```

**Stream 寫入速率**:
```promql
rate(redis_stream_messages_total{status="success"}[1m])
```

**Redis 操作 P95 延遲**:
```promql
histogram_quantile(0.95, rate(redis_operation_duration_seconds_bucket[5m]))
```

**快取命中率**:
```promql
rate(redis_cache_hits_total[5m]) /
(rate(redis_cache_hits_total[5m]) + rate(redis_cache_misses_total[5m])) * 100
```

##### 3. 業務指標

**每秒日誌接收數（按級別）**:
```promql
sum(rate(logs_received_total[1m])) by (log_level)
```

**日誌處理錯誤率**:
```promql
rate(logs_processing_errors_total[5m])
```

**活躍設備數**:
```promql
active_devices_total
```

##### 4. 系統資源指標

**CPU 使用率**:
```promql
system_cpu_usage_percent
```

**記憶體使用率**:
```promql
(system_memory_usage_bytes{type='used'} / system_memory_usage_bytes{type='total'}) * 100
```

**磁碟使用率**:
```promql
(system_disk_usage_bytes{type='used'} / system_disk_usage_bytes{type='total'}) * 100
```

#### Prometheus 操作步驟

1. 開啟瀏覽器訪問 http://localhost:9090
2. 點擊頂部 **Graph** 標籤
3. 在查詢框中輸入上述 PromQL 表達式
4. 點擊 **Execute** 執行查詢
5. 切換到 **Graph** 檢視查看時間序列圖表
6. 使用右上角的時間選擇器調整查看範圍

#### 檢查告警狀態

**訪問**: http://localhost:9090/alerts

查看可能被觸發的告警：
- **HighAPILatency**: P95 回應時間 > 500ms
- **HighErrorRate**: 5xx 錯誤率 > 5%
- **RedisStreamBacklog**: Stream 大小 > 50,000
- **HighCPUUsage**: CPU 使用率 > 80%
- **HighMemoryUsage**: 記憶體使用率 > 85%

#### 檢查抓取目標

**訪問**: http://localhost:9090/targets

確認所有監控目標狀態為 **UP**：
- `fastapi` (log-fastapi-1:8000, log-fastapi-2:8000)
- `redis` (redis-exporter:9121)
- `postgres` (postgres-exporter:9187)
- `node` (node-exporter:9100)
- `cadvisor` (cadvisor:8080)

### 在 Grafana 查看儀表板

**訪問**: http://localhost:3000

**登入資訊**:
- 帳號: `admin`
- 密碼: `admin123`

#### 查看預設儀表板

1. 登入 Grafana
2. 點擊左側選單 **Dashboards** → **Browse**
3. 選擇 **日誌收集系統效能儀表板**
4. 儀表板會自動每 **10 秒刷新**

#### 儀表板面板說明

儀表板包含 10 個監控面板，分為 4 列：

**第 1 列 - HTTP 效能**:
- **每秒請求數 (QPS)**: 監控總 QPS、成功請求、錯誤請求
  - 測試期間應看到明顯的請求峰值
  - 觀察成功率是否接近 100%
- **HTTP 請求延遲**: 顯示 P50、P95、P99 百分位數
  - 重點關注 P95 是否低於 100ms（目標值）
  - 觀察延遲分佈是否穩定

**第 2 列 - Redis 效能**:
- **Redis Stream 大小**: 監控訊息隊列堆積
  - 測試期間會看到 Stream 快速增長
  - 觀察 Worker 是否能及時消化訊息
- **Redis 快取命中率**: 評估快取效能
  - 命中率應該維持在合理水平（> 50%）
- **Redis 操作延遲**: 分析各種 Redis 操作的 P95 延遲
  - XADD、GET、SET、XREADGROUP 操作的延遲

**第 3 列 - 系統資源與業務指標**:
- **系統 CPU 使用率**: 監控 CPU 負載
  - 測試期間會看到 CPU 使用率上升
  - 觀察是否超過 80% 警戒值
- **系統記憶體使用**: 監控記憶體使用情況
  - 觀察已使用 vs 可用記憶體
- **每秒日誌接收數**: 按日誌級別統計接收量
  - 測試期間會看到各級別日誌的接收峰值

**第 4 列 - 進階指標**:
- **Redis Stream 寫入狀態**: 監控訊息寫入成功率
  - 成功寫入應接近 100%
  - 失敗寫入應該很少或為 0
- **系統磁碟使用**: 監控磁碟空間
  - 確保有足夠的磁碟空間

#### 使用技巧

1. **調整時間範圍**: 點擊右上角時間選擇器
   - 選擇「Last 15 minutes」查看測試期間數據
   - 選擇「Last 1 hour」查看完整趨勢

2. **暫停自動刷新**: 點擊右上角刷新按鈕旁的下拉選單
   - 選擇「Off」暫停刷新以仔細分析數據

3. **放大圖表**: 在圖表上拖動選擇區域
   - 可以放大查看特定時間段的細節

4. **查看原始數據**: 點擊面板標題 → **Inspect** → **Data**
   - 查看查詢返回的原始數據

### 在 Exporters 查看原始指標

#### FastAPI 應用指標

**訪問**: http://localhost:18723/metrics

**重要指標**:
```
# HTTP 請求總數
http_requests_total{method="POST",endpoint="/api/logs/batch",status="200"} 1234

# HTTP 請求延遲分佈（Histogram buckets）
http_request_duration_seconds_bucket{method="POST",endpoint="/api/logs/batch",le="0.1"} 1200
http_request_duration_seconds_bucket{method="POST",endpoint="/api/logs/batch",le="+Inf"} 1234

# Redis Stream 大小
redis_stream_size 5000

# 日誌接收總數
logs_received_total{device_id="device_000",log_level="INFO"} 100
```

#### Redis Exporter

**訪問**: http://localhost:9121/metrics

**重要指標**:
```
# Redis 連線狀態
redis_up 1

# 已使用記憶體
redis_memory_used_bytes 1234567

# 命令執行總數
redis_commands_processed_total 10000

# Stream 資訊
redis_stream_length{stream="logs_stream"} 5000
```

#### PostgreSQL Exporter

**訪問**: http://localhost:9187/metrics

**重要指標**:
```
# 資料庫連線數
pg_stat_database_numbackends{datname="logsdb"} 10

# 資料表大小
pg_stat_user_tables_n_tup_ins{relname="logs"} 10000

# 交易提交數
pg_stat_database_xact_commit{datname="logsdb"} 500
```

#### 使用 curl 查詢指標

```bash
# 查看 FastAPI 指標
curl http://localhost:18723/metrics | grep http_requests_total

# 查看 Redis Stream 大小
curl http://localhost:18723/metrics | grep redis_stream_size

# 查看 Redis Exporter 記憶體使用
curl http://localhost:9121/metrics | grep redis_memory_used_bytes

# 查看 PostgreSQL 連線數
curl http://localhost:9187/metrics | grep pg_stat_database_numbackends
```

### 使用額外監控工具

#### system_monitor.py

**位置**: `monitoring/system_monitor.py`

提供即時系統資源監控：

```bash
# 單次查看系統資訊
uv run python monitoring/system_monitor.py -s

# 持續監控（每 5 秒更新）
uv run python monitoring/system_monitor.py

# 自訂更新間隔（每 10 秒）
uv run python monitoring/system_monitor.py -i 10

# 包含 Docker 容器監控
uv run python monitoring/system_monitor.py -d

# 執行健康檢查
uv run python monitoring/system_monitor.py -c
```

**輸出範例**:
```
========================================
系統監控 - 2025-11-18 10:30:45
========================================
CPU 使用率: 45.2%
記憶體使用: 8.5GB / 16.0GB (53.1%)
磁碟使用: 120.5GB / 500.0GB (24.1%)
網路 I/O: ↑ 1.2MB/s ↓ 3.4MB/s
========================================
```

### 壓力測試監控檢查清單

執行壓力測試時，按照以下檢查清單進行監控：

#### 測試前（T-5分鐘）

- [ ] 確認所有 Docker 容器運行正常
- [ ] 檢查 Prometheus Targets 全部為 UP
- [ ] 登入 Grafana 並開啟儀表板
- [ ] 清空或記錄當前 Redis Stream 大小
- [ ] 確認沒有活躍告警

#### 測試期間（即時監控）

**在 Grafana 儀表板觀察**:
- [ ] QPS 達到預期峰值（~200 req/s 批量模式）
- [ ] P95 回應時間保持在 100ms 以下
- [ ] 錯誤率為 0% 或極低
- [ ] Redis Stream 大小穩定增長
- [ ] CPU 使用率未超過 80%
- [ ] 記憶體使用率未超過 85%

**在 Prometheus 檢查**:
- [ ] 無新告警觸發
- [ ] 所有 Targets 保持 UP 狀態

**在終端觀察**:
- [ ] 壓力測試腳本正常執行
- [ ] 無連線錯誤或超時

#### 測試後（T+5分鐘）

- [ ] 檢查測試腳本輸出的最終統計
- [ ] 確認吞吐量達到目標（≥ 10,000 logs/秒）
- [ ] 確認 P95 回應時間達標（< 100ms）
- [ ] 檢查 Redis Stream 是否被 Worker 消化
- [ ] 查看 PostgreSQL 中的日誌記錄數
- [ ] 檢查系統資源恢復正常
- [ ] 查看是否有任何錯誤日誌

#### 數據分析

```bash
# 查詢 PostgreSQL 中的日誌總數
docker exec log-postgres psql -U loguser -d logsdb -c "SELECT COUNT(*) FROM logs;"

# 查看 Redis Stream 當前大小
docker exec log-redis redis-cli XLEN logs_stream

# 查看容器資源使用
docker stats --no-stream
```

### 常見問題排查

#### 問題 1: Grafana 儀表板無數據

**排查步驟**:
1. 檢查 Prometheus 是否正常運行: `curl http://localhost:9090/-/healthy`
2. 檢查 Grafana 資料源配置: Grafana → Configuration → Data Sources
3. 確認 Prometheus Targets 狀態: http://localhost:9090/targets
4. 檢查 FastAPI 應用是否暴露 /metrics 端點: `curl http://localhost:18723/metrics`

#### 問題 2: 指標數據不準確

**可能原因**:
- Prometheus 抓取間隔導致的數據延遲（5-15秒）
- 時間範圍選擇不當
- 查詢表達式錯誤

**解決方案**:
- 等待至少 30 秒讓數據穩定
- 調整時間範圍到測試實際執行時段
- 驗證 PromQL 表達式語法

#### 問題 3: 告警誤報

**可能原因**:
- 告警閾值設定不當
- 短暫的資源峰值觸發告警

**解決方案**:
- 調整告警規則的持續時間（`for` 參數）
- 修改閾值以符合實際負載情況
- 參考 `monitoring/prometheus/alerts/app_alerts.yml`

#### 問題 4: Redis Stream 堆積

**排查步驟**:
1. 檢查 Worker 容器狀態: `docker ps | grep worker`
2. 查看 Worker 日誌: `docker logs log-worker`
3. 檢查 Worker 處理速率: Grafana 儀表板查看處理指標
4. 增加 Worker 實例數量（如需要）

### 效能調優建議

基於監控數據進行系統調優：

#### 場景 1: P95 延遲過高

**觀察**: P95 > 100ms

**調優策略**:
1. 減小批次大小（`BATCH_SIZE`）
2. 增加 FastAPI workers 數量（`docker-compose.yml:31,54`）
3. 優化資料庫連線池設定
4. 檢查是否有慢查詢

#### 場景 2: Redis Stream 堆積

**觀察**: `redis_stream_size` 持續增長

**調優策略**:
1. 增加 Worker 實例
2. 調整 Worker 批次處理大小
3. 優化資料庫寫入效能
4. 考慮使用批量插入

#### 場景 3: CPU 使用率過高

**觀察**: `system_cpu_usage_percent` > 80%

**調優策略**:
1. 減少並發請求數（`CONCURRENT_LIMIT`）
2. 優化程式碼中的 CPU 密集操作
3. 考慮垂直擴展（增加 CPU 核心）
4. 實施限流機制

#### 場景 4: 記憶體使用率過高

**觀察**: 記憶體使用率 > 85%

**調優策略**:
1. 調整 Redis maxmemory 設定（`docker-compose.yml:110`）
2. 優化批次處理大小避免記憶體峰值
3. 檢查是否有記憶體洩漏
4. 考慮垂直擴展（增加記憶體）

### 監控最佳實踐

#### 1. 建立基線

在正式壓力測試前，先進行小規模測試建立效能基線：

```bash
# 小規模測試（10 設備 × 10 日誌 = 100 筆）
# 修改 tests/stress_test.py 中的配置
NUM_DEVICES = 10
LOGS_PER_DEVICE = 10
```

記錄基線數據：
- 正常 QPS
- 正常 P95 延遲
- 正常資源使用率

#### 2. 漸進式負載測試

逐步增加負載，觀察系統行為：

1. **階段 1**: 10 設備 × 10 日誌 = 100 筆
2. **階段 2**: 50 設備 × 50 日誌 = 2,500 筆
3. **階段 3**: 100 設備 × 100 日誌 = 10,000 筆
4. **階段 4**: 200 設備 × 100 日誌 = 20,000 筆（壓力測試）

#### 3. 長時間穩定性測試

除了峰值測試，也要進行長時間穩定性測試：

```bash
# 修改測試腳本持續運行
# 觀察 30 分鐘或 1 小時的系統行為
# 檢查是否有記憶體洩漏、資源洩漏等問題
```

#### 4. 記錄測試結果

每次測試後記錄關鍵指標：

| 測試時間 | 總日誌數 | 吞吐量 | P95 延遲 | CPU 峰值 | 記憶體峰值 | 錯誤率 |
|---------|---------|--------|----------|----------|-----------|--------|
| 2025-11-18 10:00 | 10,000 | 12,500 logs/s | 85ms | 65% | 55% | 0% |

#### 5. 定期監控審查

定期（每週/每月）審查監控數據：
- 識別效能趨勢
- 預測容量需求
- 優化告警規則
- 更新效能目標

### 總結

完整的壓力測試監控流程包括：

1. **準備階段**:
   - ✅ 啟動監控系統
   - ✅ 確認服務狀態
   - ✅ 準備檢查清單

2. **執行階段**:
   - ✅ 運行壓力測試腳本
   - ✅ 即時監控 Grafana 儀表板
   - ✅ 檢查 Prometheus 告警
   - ✅ 觀察系統資源

3. **分析階段**:
   - ✅ 查看測試腳本輸出
   - ✅ 分析 Grafana 圖表
   - ✅ 查詢 Prometheus 指標
   - ✅ 檢查 Exporters 數據

4. **優化階段**:
   - ✅ 識別效能瓶頸
   - ✅ 實施調優策略
   - ✅ 驗證改進效果
   - ✅ 記錄測試結果

透過這套完整的監控體系，可以全面了解系統在壓力測試下的行為，及時發現問題，並持續優化效能。

---

**文檔版本**: 1.1
**最後更新**: 2025-11-18
**維護者**: Log Collection System Team
