# PostgreSQL 連線池監控系統

本文檔說明如何使用 PostgreSQL 連線池監控系統來監控連線池運作、檢測連線洩漏、評估 max_connections 設定以及觀察系統負載對資料庫連線的影響。

## 目錄

1. [功能概述](#功能概述)
2. [監控指標](#監控指標)
3. [部署方式](#部署方式)
4. [查看監控數據](#查看監控數據)
5. [告警規則](#告警規則)
6. [故障排除](#故障排除)

## 功能概述

PostgreSQL 連線池監控系統提供以下功能:

### 1. 監控連線池是否正常運作
- 即時追蹤連線池大小、使用中連線和可用連線
- 監控連線獲取時間和成功率
- 檢測連線池耗盡情況

### 2. 檢測連線洩漏 (Connection Leak)
- 追蹤長時間運行的連線 (> 1分鐘、5分鐘、15分鐘)
- 識別 `idle in transaction` 狀態的連線
- 累計連線洩漏總數統計

### 3. 評估是否需要調整 max_connections
- 監控當前連線數 vs max_connections 的比例
- 提供連線使用率趨勢分析
- 自動告警當連線數接近上限

### 4. 觀察系統負載對資料庫連線的影響
- 追蹤每個 CPU 核心的平均連線數
- 關聯連線狀態與系統資源使用
- 監控等待鎖的連線數量

## 監控指標

### 連線池指標

| 指標名稱 | 說明 | 用途 |
|---------|------|------|
| `pg_pool_size` | 當前連線池大小 | 監控連線池規模 |
| `pg_pool_max_size` | 連線池最大大小 | 了解連線池容量上限 |
| `pg_pool_in_use_connections` | 使用中的連線數 | 評估連線池負載 |
| `pg_pool_available_connections` | 可用連線數 | 檢測連線池是否即將耗盡 |
| `pg_connection_acquire_duration_seconds` | 連線獲取時間 (直方圖) | 分析連線獲取性能 |
| `pg_connection_acquire_total` | 連線獲取統計 (計數器) | 追蹤成功/失敗/超時次數 |

### 連線洩漏檢測指標

| 指標名稱 | 說明 | 用途 |
|---------|------|------|
| `pg_connection_leaked_total` | 累計洩漏連線總數 | 識別連線洩漏趨勢 |
| `pg_connection_long_running_total` | 長時間運行的連線數 | 按時間閾值分類 (60s/300s/900s) |
| `pg_connections_idle_in_transaction` | Idle in transaction 連線數 | 檢測未提交/回滾的事務 |
| `pg_connections_waiting` | 等待鎖的連線數 | 識別鎖爭用問題 |

### 資料庫連線統計指標

| 指標名稱 | 說明 | 用途 |
|---------|------|------|
| `pg_max_connections` | PostgreSQL max_connections 設定值 | 了解連線數上限 |
| `pg_connection_usage_ratio` | 連線使用率 (當前連線數/max_connections) | 評估是否需要調整設定 |
| `pg_connections_active_queries` | 活躍查詢連線數 | 監控實際工作負載 |
| `pg_connections_per_cpu_core` | 每個 CPU 核心的平均連線數 | 評估系統負載影響 |
| `pg_connection_age_seconds` | 連線年齡分佈 (直方圖) | 分析連線持續時間 |

## 部署方式

### 1. 構建並啟動監控服務

```bash
# 在專案根目錄執行
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d --build postgres-connection-monitor
```

### 2. 驗證服務運行狀態

```bash
# 檢查容器狀態
docker ps | grep postgres-connection-monitor

# 查看服務日誌
docker logs log-postgres-connection-monitor

# 測試健康檢查
curl http://localhost:9188/health

# 查看原始 metrics
curl http://localhost:9188/metrics
```

### 3. 重啟 Prometheus 以載入新配置

```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml restart prometheus
```

### 4. 檢查 Prometheus targets

訪問 `http://localhost:9090/targets`，確認 `postgres-connection` job 顯示為 UP 狀態。

## 查看監控數據

### 方法一: 使用專用 Grafana 儀表板

1. 訪問 Grafana: `http://localhost:3000`
2. 登入 (預設帳號: `admin` / 密碼: `admin123`)
3. 導入儀表板:
   - 點擊左側菜單的 `+` → `Import`
   - 選擇 `Upload JSON file`
   - 上傳檔案: `monitoring/grafana/dashboards/postgres-connection-monitor.json`
   - 選擇 Prometheus 資料源
   - 點擊 `Import`

### 方法二: 在現有儀表板中查看

訪問現有的「日誌收集系統 - 整合效能儀表板」，已包含基本的 PostgreSQL 連線監控面板。

### 方法三: 使用 Prometheus 查詢

訪問 Prometheus UI (`http://localhost:9090/graph`)，執行以下 PromQL 查詢:

**檢查連線池使用率:**
```promql
(pg_pool_in_use_connections / pg_pool_max_size) * 100
```

**檢測連線洩漏:**
```promql
pg_connection_long_running_total{threshold_seconds="300"}
```

**評估連線數是否接近上限:**
```promql
(sum(pg_stat_activity_count{datname="logsdb"}) / pg_max_connections) * 100
```

## 告警規則

系統已配置以下重要告警 (位於 `monitoring/prometheus/alerts/postgres_connection_alerts.yml`):

### 連線池相關告警

| 告警名稱 | 觸發條件 | 嚴重程度 | 建議處理方式 |
|---------|---------|----------|------------|
| `HighConnectionPoolUsage` | 連線池使用率 > 80% (持續5分鐘) | warning | 考慮增加連線池大小 |
| `ConnectionPoolExhausted` | 沒有可用連線 (持續2分鐘) | critical | 立即檢查應用程式連線使用情況 |
| `SlowConnectionAcquisition` | P95 連線獲取時間 > 1秒 (持續5分鐘) | warning | 檢查連線池配置或資料庫性能 |

### 連線洩漏告警

| 告警名稱 | 觸發條件 | 嚴重程度 | 建議處理方式 |
|---------|---------|----------|------------|
| `ConnectionLeakDetected` | 檢測到運行超過5分鐘的連線 | warning | 檢查應用程式代碼,確保連線正確釋放 |
| `TooManyLongRunningConnections5Min` | 超過5個連線運行 > 5分鐘 | warning | 可能存在連線洩漏,檢查代碼 |
| `TooManyLongRunningConnections15Min` | 超過2個連線運行 > 15分鐘 | critical | 極可能是連線洩漏,立即處理 |
| `TooManyIdleInTransactionConnections` | Idle in transaction 連線 > 5個 (持續10分鐘) | warning | 檢查事務是否正確提交/回滾 |

### 連線限制告警

| 告警名稱 | 觸發條件 | 嚴重程度 | 建議處理方式 |
|---------|---------|----------|------------|
| `HighDatabaseConnections` | 連線數 > max_connections 的 70% (持續10分鐘) | warning | 考慮優化連線使用或增加 max_connections |
| `DatabaseConnectionsNearLimit` | 連線數 > max_connections 的 90% (持續5分鐘) | critical | 立即處理,可能導致新連線被拒絕 |
| `HighConnectionsPerCPU` | 每個 CPU 核心 > 10個活躍連線 (持續10分鐘) | warning | 可能影響性能,優化查詢或增加資源 |

### 優化建議告警

| 告警名稱 | 觸發條件 | 嚴重程度 | 建議處理方式 |
|---------|---------|----------|------------|
| `SuggestIncreaseMaxConnections` | 連線使用率 > 85% 且有獲取失敗 (持續20分鐘) | info | 考慮增加 max_connections 設定 |
| `SuggestOptimizeConnectionUsage` | 長時間連線 > 5個 且連線池使用率 > 70% | info | 優化查詢或連線使用模式 |

## 故障排除

### 問題1: 監控服務無法啟動

**症狀:** `postgres-connection-monitor` 容器無法啟動或頻繁重啟

**排查步驟:**
```bash
# 查看容器日誌
docker logs log-postgres-connection-monitor

# 檢查 PostgreSQL 連線
docker exec log-postgres-connection-monitor python -c "import asyncpg; import asyncio; asyncio.run(asyncpg.connect('postgresql://loguser:logpass@postgres:5432/logsdb'))"
```

**常見原因:**
- PostgreSQL 服務未啟動
- 資料庫連線字串錯誤
- 依賴套件未正確安裝

### 問題2: Prometheus 無法抓取 metrics

**症狀:** Prometheus targets 頁面顯示 `postgres-connection` job 為 DOWN 狀態

**排查步驟:**
```bash
# 測試 metrics 端點
curl http://localhost:9188/metrics

# 從 Prometheus 容器內測試
docker exec log-prometheus wget -O- http://postgres-connection-monitor:9188/metrics
```

**常見原因:**
- 監控服務未正確啟動
- Docker 網路配置問題
- 防火牆阻擋端口 9188

### 問題3: 告警未觸發

**症狀:** 即使連線池使用率很高,但沒有收到告警

**排查步驟:**
```bash
# 檢查 Prometheus 告警規則是否載入
curl http://localhost:9090/api/v1/rules | jq

# 查看 Prometheus 配置
docker exec log-prometheus cat /etc/prometheus/prometheus.yml

# 檢查 AlertManager 狀態
curl http://localhost:9093/api/v1/status
```

**常見原因:**
- 告警規則文件未正確掛載
- AlertManager 配置錯誤
- 告警條件未滿足持續時間要求

### 問題4: 指標數據不準確

**症狀:** Grafana 顯示的連線數與實際不符

**排查步驟:**
```bash
# 直接查詢 PostgreSQL
docker exec log-postgres psql -U loguser -d logsdb -c "SELECT count(*) FROM pg_stat_activity WHERE datname='logsdb';"

# 查看原始 metrics
curl http://localhost:9188/metrics | grep pg_connections

# 比對兩者數據
```

**常見原因:**
- 監控服務採樣間隔過長
- PostgreSQL 統計資訊未及時更新
- 時區設定不一致

### 問題5: 連線洩漏誤報

**症狀:** 告警顯示連線洩漏,但檢查後發現是正常的長查詢

**解決方案:**
1. 調整洩漏檢測閾值 (修改 `postgres_connection_monitor.py` 中的 `leak_threshold_seconds`)
2. 優化慢查詢,減少長時間運行的合法查詢
3. 為特定查詢添加白名單 (需修改監控腳本)

## 進階配置

### 調整連線池參數

編輯 `monitoring/postgres_connection_monitor.py`:

```python
self.pool = await asyncpg.create_pool(
    self.db_url,
    min_size=2,      # 調整最小連線數
    max_size=10,     # 調整最大連線數
    command_timeout=60  # 調整命令超時時間
)
```

### 修改採樣間隔

編輯 `monitoring/postgres_connection_monitor.py`:

```python
# 在 monitor_loop 函數中
await asyncio.sleep(10)  # 改為您想要的秒數
```

### 自定義告警閾值

編輯 `monitoring/prometheus/alerts/postgres_connection_alerts.yml`,調整各告警的閾值和持續時間。

## 最佳實踐

1. **定期檢查連線使用率趨勢**
   - 每週查看連線池使用率圖表
   - 在流量高峰期特別關注

2. **建立連線洩漏檢測流程**
   - 當收到連線洩漏告警時,立即檢查應用程式日誌
   - 使用 PostgreSQL 的 `pg_stat_activity` 視圖定位問題查詢

3. **適時調整 max_connections**
   - 根據實際負載和硬體資源調整
   - 公式參考: `max_connections = (可用記憶體 / 10MB) * 0.8`
   - 留 20% 餘量給系統和其他連線

4. **監控與優化並行**
   - 不僅監控指標,還要分析趨勢
   - 結合應用程式日誌進行根因分析
   - 定期優化慢查詢和連線使用模式

## 相關資源

- [PostgreSQL 官方文檔 - pg_stat_activity](https://www.postgresql.org/docs/current/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW)
- [Prometheus 查詢語法](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana 儀表板設計最佳實踐](https://grafana.com/docs/grafana/latest/best-practices/)
- [連線池最佳實踐](https://wiki.postgresql.org/wiki/Number_Of_Database_Connections)
