# 效能比較指南

## 📊 核心效能比較的三大指標

基於系統架構差異和實際測試需求,以下三種量測方式最能反映主系統與對照組的效能差異:

### 1️⃣ 日誌吞吐量 (Logs Throughput) - logs/s
**最重要的核心指標**

- **定義**: 系統每秒實際處理的日誌數量
- **重要性**: 直接反映系統的處理能力,是最核心的業務指標
- **查詢語法**: `sum(irate(logs_received_total[5s]))`
- **預期差異**:
  - 主系統目標: > 10,000 logs/s
  - 對照組實測: ~382 logs/s
  - 效能提升: **20-30 倍**

### 2️⃣ HTTP QPS (Queries Per Second) - req/s
**API 處理效率指標**

- **定義**: 系統每秒處理的 HTTP 請求數量
- **重要性**: 反映 API 層的處理效率和並發能力
- **查詢語法**: `sum(irate(http_requests_total[5s]))`
- **預期差異**:
  - 主系統目標: > 2,000 req/s
  - 對照組實測: ~75 req/s
  - 效能提升: **約 27 倍**
- **換算關係**: `吞吐量 ≈ QPS × batch_size`

### 3️⃣ PostgreSQL 插入速率 (PG Insert Rate) - rows/s
**資料持久化能力指標**

- **定義**: PostgreSQL 每秒實際插入的資料列數
- **重要性**: 反映後端資料庫的寫入能力和整體系統瓶頸
- **查詢語法**: `sum(irate(pg_stat_database_tup_inserted{datname="logsdb"}[5s]))`
- **架構差異**:
  - 主系統: Redis Stream 緩衝 + Worker 批次寫入
  - 對照組: 同步直寫 PostgreSQL
- **預期差異**: 主系統有更平穩的寫入曲線

---

## 🔧 統一配置說明

為確保公平比較,所有監控和匯出配置已統一:

### Grafana Dashboard 配置
| 項目 | 統一設定 | 說明 |
|------|---------|------|
| 時間窗口 | `irate[5s]` | 捕捉瞬時峰值,適合短測試週期 |
| 採樣間隔 | `1s` | 高解析度數據採集 |
| 圖表標籤 | 1️⃣ 2️⃣ 3️⃣ | 清楚標示核心指標優先順序 |
| 顏色編碼 | 綠/紅/藍 | 主系統與對照組使用相同配色 |

### CSV 匯出欄位
兩個系統匯出的 CSV 檔案包含相同的核心指標:

```csv
timestamp, 1_logs_throughput (1️⃣ 日誌吞吐量 (logs/s)), 2_http_qps (2️⃣ HTTP QPS (req/s)), 3_pg_insert_rate (3️⃣ PG 插入速率 (rows/s))
```

**主系統額外指標**:
- `redis_messages_per_second (Redis 訊息 (msg/s) - 主系統架構特有)`

---

## 📈 使用指南

### 1. Grafana 即時監控

**主系統儀表板**:
- URL: http://localhost:3000
- Dashboard: "日誌收集系統 - 整合效能儀表板 (Redis + Worker)"
- 核心圖表: "核心效能指標對比 - 主系統 (Redis + Worker 架構)"

**對照組儀表板**:
- URL: http://localhost:3001
- Dashboard: "對照組 - 簡化系統效能儀表板"
- 核心圖表: "核心效能指標對比 - 對照組 (簡化架構)"

### 2. 數據匯出與分析

**主系統匯出**:
```bash
cd monitoring/scripts
python export_throughput_metrics.py --duration 1h
```

**對照組匯出**:
對照組的壓力測試腳本會自動匯出指標:
```bash
cd control-group
uv run stress_test_simple.py
```

輸出位置: `test_file/control_group_throughput_metrics.csv`

### 3. Excel 數據比較

兩個系統的 CSV 檔案具有相同的欄位結構,可直接在 Excel 中進行:

1. **並排比較**: 使用 VLOOKUP 或 Power Query 合併數據
2. **圖表疊加**: 將兩個系統的三大指標繪製在同一圖表
3. **統計分析**: 計算平均值、峰值、標準差等統計量

---

## 🎯 效能比較範例

### 實測數據摘要

| 指標 | 主系統 (優化) | 對照組 (簡化) | 提升倍數 |
|------|-------------|-------------|---------|
| **吞吐量** | 11,127 logs/s | 382 logs/s | **29.1x** |
| **QPS** | 2,225 req/s | 75 req/s | **29.7x** |
| **PG 插入** | 穩定批次寫入 | 同步單筆寫入 | 架構優勢 |

### 架構差異對照

| 功能 | 主系統 | 對照組 |
|------|--------|--------|
| 負載平衡 | ✅ Nginx | ❌ 直連 API |
| 連接池 | ✅ PostgreSQL Pool | ❌ 無優化 |
| 非同步佇列 | ✅ Redis Stream | ❌ 無緩衝 |
| 並行處理 | ✅ 多 Worker | ❌ 單線程 |
| 批次寫入 | ✅ 批次優化 | ❌ 同步直寫 |

---

## 💡 關鍵發現

1. **吞吐量提升**: 主系統達到 29.1 倍效能提升,超越 20-30 倍目標
2. **架構優勢**: Redis 非同步佇列有效解耦請求處理與資料持久化
3. **測量一致性**: 統一使用 `irate[5s]` 確保公平比較
4. **公式驗證**: `吞吐量 ≈ QPS × batch_size` 在兩個系統中都成立

---

## 📝 注意事項

1. **時間窗口**: `irate[5s]` 適合短測試週期 (0.9s),長測試可考慮 `rate[30s]`
2. **數據篩選**: 已移除自動中位數篩選,建議在分析階段使用 Excel 或 pandas 處理
3. **Redis 指標**: 僅主系統有此指標,反映架構特性而非效能缺陷
4. **測試環境**: 確保兩個系統在相同的硬體和網路環境下測試

---

## 🔗 相關檔案

- 主系統 Dashboard: `monitoring/grafana/dashboards/log-collection-dashboard.json`
- 對照組 Dashboard: `control-group/monitoring/grafana/dashboards/control-group-dashboard.json`
- 主系統匯出腳本: `monitoring/scripts/export_throughput_metrics.py`
- 對照組測試腳本: `control-group/stress_test_simple.py`

---

最後更新: 2025-11-26
