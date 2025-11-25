# 系統吞吐量指標匯出工具

## 功能說明

`export_throughput_metrics.py` 可以從 Prometheus 查詢並匯出 Grafana 儀表板中「系統吞吐量 (Throughput)」圖表的所有指標資料到 CSV 檔案。

## 匯出的指標

此工具會匯出以下 5 個關鍵指標:

1. **每秒日誌數 (30s 平均)** - `sum(irate(logs_received_total[30s]))`
2. **每秒日誌數 (1m 平滑)** - `sum(irate(logs_received_total[1m]))`
3. **每秒請求數 (批量請求)** - `sum(irate(http_requests_total[30s]))`
4. **PostgreSQL 每秒插入行數** - `sum(irate(pg_stat_database_tup_inserted{datname="logsdb"}[30s]))`
5. **Redis Stream 每秒訊息數** - `sum(irate(redis_stream_messages_total{status='success'}[30s]))`

## 環境準備

### 1. 安裝依賴套件

```bash
# 使用 uv 安裝 (推薦)
source .venv/bin/activate
uv pip install requests

# 或使用 pip
pip install requests
```

### 2. 確認 Prometheus 運行

```bash
# 測試 Prometheus API 連線
curl http://localhost:9090/api/v1/query?query=up
```

## 使用方式

### 基本用法

```bash
# 啟用虛擬環境
source .venv/bin/activate

# 匯出最近 1 小時的資料 (預設)
python monitoring/scripts/export_throughput_metrics.py

# 匯出最近 10 分鐘的資料
python monitoring/scripts/export_throughput_metrics.py --duration 10m

# 匯出最近 2 小時的資料
python monitoring/scripts/export_throughput_metrics.py --duration 2h
```

### 指定時間範圍

```bash
# 匯出指定時間段的資料
python monitoring/scripts/export_throughput_metrics.py \
  --start "2024-11-25T10:00:00" \
  --end "2024-11-25T11:00:00"
```

### 自訂輸出檔名

```bash
# 指定輸出檔名
python monitoring/scripts/export_throughput_metrics.py \
  --duration 30m \
  --output my_metrics.csv
```

### 指定 Prometheus URL

```bash
# 如果 Prometheus 不在 localhost:9090
python monitoring/scripts/export_throughput_metrics.py \
  --duration 1h \
  --prometheus http://prometheus:9090
```

## 輸出格式

CSV 檔案包含以下欄位:

- `timestamp`: 時間戳記 (格式: YYYY-MM-DD HH:MM:SS)
- `logs_per_second_30s (每秒日誌數 (logs/s) - 30s 平均)`: 30 秒平均日誌數
- `logs_per_second_1m (每秒日誌數 (logs/s) - 1m 平滑)`: 1 分鐘平滑日誌數
- `requests_per_second (每秒請求數 (req/s) - 批量請求)`: 批量 API 請求數
- `pg_inserts_per_second (PostgreSQL 每秒插入行數 (rows/s))`: PostgreSQL 插入速率
- `redis_messages_per_second (Redis Stream 每秒訊息數 (msg/s))`: Redis Stream 訊息處理速率

### 範例輸出

```csv
timestamp,logs_per_second_30s (...),logs_per_second_1m (...),requests_per_second (...),pg_inserts_per_second (...),redis_messages_per_second (...)
2025-11-25 08:04:41,0.0,0.0,2.0,790.08,0.0
2025-11-25 08:04:42,0.0,0.0,2.0,790.08,0.0
2025-11-25 08:04:44,1056.0,1056.0,179.0,790.08,177.0
...
```

## 執行範例

### 範例 1: 快速查看最近 10 分鐘的效能

```bash
source .venv/bin/activate
python monitoring/scripts/export_throughput_metrics.py --duration 10m
```

輸出:
```
📊 開始查詢吞吐量指標...
   時間範圍: 2025-11-25 08:04:41 ~ 2025-11-25 08:14:41
   查詢指標數: 5

   查詢: 每秒日誌數 (logs/s) - 30s 平均
      ✅ 取得 336 筆資料
   查詢: 每秒日誌數 (logs/s) - 1m 平滑
      ✅ 取得 366 筆資料
   查詢: 每秒請求數 (req/s) - 批量請求
      ✅ 取得 601 筆資料
   查詢: PostgreSQL 每秒插入行數 (rows/s)
      ✅ 取得 601 筆資料
   查詢: Redis Stream 每秒訊息數 (msg/s)
      ✅ 取得 336 筆資料

💾 寫入 CSV: throughput_metrics.csv
✅ 匯出完成!
   檔案: throughput_metrics.csv
   資料筆數: 601
   時間範圍: 2025-11-25 08:04:41 ~ 2025-11-25 08:14:41

📈 統計摘要:
   每秒日誌數 (logs/s) - 30s 平均:
      最大值: 10010.01
      最小值: 0.00
      平均值: 267.95
   每秒請求數 (req/s) - 批量請求:
      最大值: 2004.00
      最小值: 1.08
      平均值: 31.96
   ...
```

### 範例 2: 匯出壓測期間的資料

```bash
source .venv/bin/activate
python monitoring/scripts/export_throughput_metrics.py \
  --start "2024-11-25T14:30:00" \
  --end "2024-11-25T14:35:00" \
  --output stress_test_results.csv
```

## 疑難排解

### 問題 1: 無法連接到 Prometheus

**錯誤訊息:**
```
❌ 查詢失敗: sum(irate(logs_received_total[30s]))
   錯誤: ...
```

**解決方法:**
1. 確認 Prometheus 正在運行:
   ```bash
   docker ps | grep prometheus
   ```

2. 測試 API 連線:
   ```bash
   curl http://localhost:9090/api/v1/query?query=up
   ```

3. 如果 Prometheus 在不同的位置,使用 `--prometheus` 參數指定 URL

### 問題 2: 沒有資料

**錯誤訊息:**
```
❌ 沒有任何資料可匯出
```

**可能原因:**
1. 查詢的時間範圍內沒有資料
2. 指標名稱不存在
3. 服務尚未產生指標

**解決方法:**
1. 使用較長的時間範圍 (例如 `--duration 1h`)
2. 在 Prometheus Web UI 確認指標是否存在: http://localhost:9090/graph
3. 確認服務正在運行並產生指標

### 問題 3: ModuleNotFoundError: No module named 'requests'

**解決方法:**
```bash
source .venv/bin/activate
uv pip install requests
```

## 進階用法

### 與其他工具整合

#### 1. 使用 Excel/LibreOffice 分析

直接用 Excel 或 LibreOffice Calc 開啟 CSV 檔案進行分析和繪圖。

#### 2. 使用 pandas 分析

```python
import pandas as pd

# 讀取 CSV
df = pd.read_csv('throughput_metrics.csv')

# 計算統計資訊
print(df.describe())

# 繪製圖表
import matplotlib.pyplot as plt
df.plot(x='timestamp', y=['logs_per_second_30s (...)'])
plt.show()
```

#### 3. 自動化定期匯出

建立 cron job 定期匯出資料:

```bash
# 每小時匯出一次
0 * * * * cd /path/to/project && source .venv/bin/activate && python monitoring/scripts/export_throughput_metrics.py --duration 1h --output /var/log/metrics/$(date +\%Y\%m\%d_\%H).csv
```

## 相關文件

- [Prometheus 查詢語法](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana 儀表板配置](../grafana/dashboards/log-collection-dashboard.json)
- [系統監控架構](../README.md)
