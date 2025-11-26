# 系統性能比較指標指南

## 比較目標
比較 **control-group** (簡化系統) 和 **主系統** (Redis + Worker) 的性能差異。

## 核心比較指標

### 1. 吞吐量比較 (Throughput)

| 指標名稱 | PromQL 查詢 | 說明 |
|---------|------------|------|
| 日誌接收速率 | `sum(rate(logs_received_total[30s]))` | 每秒接收的日誌數量 |
| HTTP 請求速率 | `sum(rate(http_requests_total[30s]))` | 每秒處理的 HTTP 請求數 |
| PostgreSQL 插入速率 | `sum(rate(pg_stat_database_tup_inserted{datname="logsdb"}[30s]))` | PostgreSQL 每秒插入的行數 |
| Redis 訊息速率* | `sum(rate(redis_stream_messages_total{status='success'}[30s]))` | Redis Stream 每秒處理的訊息數 (僅主系統) |

**評估標準：**
- 主系統預期：10,000+ logs/s
- 對照組預期：100-500 logs/s
- **比率：** 主系統應為對照組的 20-100 倍

---

### 2. 延遲比較 (Latency)

| 指標名稱 | PromQL 查詢 | 目標值 |
|---------|------------|--------|
| HTTP P50 延遲 | `histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` | < 50ms (主系統) vs < 100ms (對照組) |
| HTTP P95 延遲 | `histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` | < 200ms (主系統) vs < 500ms (對照組) |
| HTTP P99 延遲 | `histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))` | < 500ms (主系統) vs < 1s (對照組) |
| PG 查詢延遲 | `histogram_quantile(0.95, sum(rate(postgres_query_duration_seconds_bucket[5m])) by (le))` | 越低越好 |

**評估標準：**
- 主系統延遲應為對照組的 20%-50%
- P99 延遲特別重要，反映尾延遲

---

### 3. 資源使用率比較

| 指標名稱 | PromQL 查詢 | 說明 |
|---------|------------|------|
| CPU 使用率 | `rate(container_cpu_usage_seconds_total[30s]) * 100` | 容器 CPU 使用百分比 |
| 記憶體使用 | `container_memory_usage_bytes` | 容器記憶體使用量 (bytes) |
| 網路接收速率 | `rate(container_network_receive_bytes_total[30s])` | 網路接收速度 (bytes/s) |
| 網路發送速率 | `rate(container_network_transmit_bytes_total[30s])` | 網路發送速度 (bytes/s) |

**評估標準：**
- **效率指標 = 吞吐量 / 資源使用率**
- 主系統應在更高吞吐量下保持合理的資源使用
- 對照組可能在低負載時資源使用率較低，但無法擴展

---

### 4. PostgreSQL 性能比較

| 指標名稱 | PromQL 查詢 | 說明 |
|---------|------------|------|
| 活躍連線數 | `pg_stat_database_numbackends{datname="logsdb"}` | PostgreSQL 活躍連線數 |
| 事務提交率 | `rate(pg_stat_database_xact_commit{datname="logsdb"}[30s])` | 每秒提交的事務數 |
| 事務回滾率 | `rate(pg_stat_database_xact_rollback{datname="logsdb"}[30s])` | 每秒回滾的事務數 |
| 緩存命中率 | `rate(pg_stat_database_blks_hit{datname="logsdb"}[30s]) / (rate(pg_stat_database_blks_hit{datname="logsdb"}[30s]) + rate(pg_stat_database_blks_read{datname="logsdb"}[30s]))` | 資料庫緩存效率 |
| 死鎖數 | `rate(pg_stat_database_deadlocks{datname="logsdb"}[30s])` | 每秒發生的死鎖數 |

**評估標準：**
- 主系統應有更高的事務提交率
- 對照組可能有更多的死鎖和事務回滾
- 緩存命中率應 > 95%

---

### 5. 錯誤率和穩定性比較

| 指標名稱 | PromQL 查詢 | 目標值 |
|---------|------------|--------|
| HTTP 5xx 錯誤率 | `sum(rate(http_requests_total{status=~"5.."}[30s])) / sum(rate(http_requests_total[30s])) * 100` | < 0.1% |
| 日誌處理錯誤率 | `rate(logs_processing_errors_total[30s])` | 接近 0 |
| PostgreSQL 連線錯誤* | `rate(postgres_errors_total{error_type="connection_error"}[30s])` | 接近 0 (主系統) |

**評估標準：**
- 對照組在高負載時錯誤率預期會顯著上升
- 主系統應保持低錯誤率即使在高負載下

---

## 比較方法

### 方法 1：Grafana 統一儀表板

創建一個包含兩個系統指標的 Grafana 儀表板：

```promql
# 範例：日誌吞吐量比較
sum(rate(logs_received_total{cluster="log-collection-system"}[30s])) # 主系統
sum(rate(logs_received_total{cluster="control-group-simple"}[30s]))  # 對照組
```

**優點：** 即時比較，視覺化效果好

---

### 方法 2：使用現有的比較腳本

專案中已有比較工具：
```bash
# 運行壓力測試並比較
cd /Users/pololin/python_project/High-Performance-Log-Collection-system
python compare_throughput.py
```

**優點：** 自動化測試，生成 CSV 報告

---

### 方法 3：Prometheus 查詢 API

```bash
# 查詢主系統的日誌速率
curl -G 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum(rate(logs_received_total{cluster="log-collection-system"}[30s]))'

# 查詢對照組的日誌速率
curl -G 'http://localhost:9091/api/v1/query' \
  --data-urlencode 'query=sum(rate(logs_received_total{cluster="control-group-simple"}[30s]))'
```

**優點：** 編程式訪問，可集成到自動化腳本

---

## 壓力測試建議

### 測試場景

| 測試類型 | 描述 | 預期結果 |
|---------|------|---------|
| 低負載測試 | 10 logs/s，持續 1 分鐘 | 兩系統性能相近 |
| 中負載測試 | 1,000 logs/s，持續 5 分鐘 | 主系統開始顯示優勢 |
| 高負載測試 | 10,000 logs/s，持續 10 分鐘 | 對照組出現延遲/錯誤，主系統穩定 |
| 峰值測試 | 50,000 logs/s，持續 30 秒 | 對照組崩潰/拒絕服務，主系統降級服務 |
| 持久測試 | 5,000 logs/s，持續 1 小時 | 測試穩定性和資源洩漏 |

### 測試命令

```bash
# 對主系統進行壓力測試
cd /Users/pololin/python_project/High-Performance-Log-Collection-system
python stress_test.py --target-qps 10000 --duration 60

# 對對照組進行壓力測試
cd /Users/pololin/python_project/High-Performance-Log-Collection-system/control-group
python stress_test_simple.py --target-qps 1000 --duration 60
```

---

## 關鍵性能指標 (KPI) 摘要

以下是最重要的 5 個比較指標：

1. **峰值吞吐量**
   - 查詢：`max_over_time(sum(rate(logs_received_total[30s]))[10m:])`
   - 預期：主系統 > 10,000 logs/s，對照組 < 500 logs/s

2. **P95 延遲**
   - 查詢：`histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))`
   - 預期：主系統 < 200ms，對照組 < 500ms

3. **錯誤率**
   - 查詢：`sum(rate(http_requests_total{status=~"5.."}[30s])) / sum(rate(http_requests_total[30s]))`
   - 預期：兩系統都 < 0.1%

4. **資源效率** (每 CPU 核心的吞吐量)
   - 查詢：`sum(rate(logs_received_total[30s])) / sum(rate(container_cpu_usage_seconds_total[30s]))`
   - 預期：主系統效率更高

5. **PostgreSQL 連線數**
   - 查詢：`pg_stat_database_numbackends{datname="logsdb"}`
   - 預期：主系統使用連接池，連線數更穩定且更少

---

## 附註

### 時間窗口選擇
- **瞬時峰值**：使用 `irate[5s]` 或 `rate[30s]`
- **短期趨勢**：使用 `rate[5m]`
- **長期平均**：使用 `rate[1h]`

### Prometheus 配置差異
- **主系統**：1秒抓取間隔 (捕捉短測試峰值)
- **對照組**：15秒抓取間隔 (標準配置)

這意味著主系統的數據更精細，更適合捕捉短時間的性能峰值。

---

## 下一步

1. **建立統一比較儀表板**：使用 Grafana 創建一個包含兩個系統所有關鍵指標的儀表板
2. **自動化測試**：編寫腳本定期運行比較測試
3. **設定告警**：當性能差異超出預期時發送告警
4. **生成報告**：定期生成性能比較報告，追蹤改進趨勢
