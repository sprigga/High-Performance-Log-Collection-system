import csv

# 讀取CSV檔案，處理BOM字符
high_throughput_data = []
row_count = 0
skipped_rows = 0

# 讀取CSV檔案，處理BOM字符
import os
from pathlib import Path

# 獲取當前腳本所在目錄的根目錄
script_dir = Path(__file__).parent
test_file_dir = script_dir / "test_file"
csv_file_path = test_file_dir / "throughput_metrics_20251125_090719.csv"

with open(csv_file_path, 'r', encoding='utf-8-sig') as csvfile:
    # 使用utf-8-sig編碼來自動處理BOM
    reader = csv.DictReader(csvfile)

    for row in reader:
        row_count += 1
        # 檢查是否所有必要的欄位都存在且不為空
        # 注意：timestamp欄位名稱可能包含BOM字符
        timestamp_key = None
        logs_30s_key = None

        for key in row.keys():
            if key.strip() == 'timestamp':
                timestamp_key = key
            elif key.startswith('logs_per_second_30s'):
                logs_30s_key = key

        # 如果找不到必要的欄位名稱，跳過這行
        if not logs_30s_key or not timestamp_key:
            skipped_rows += 1
            continue

        # 取得 'logs_per_second_30s' 欄位的值
        try:
            logs_per_second_30s_str = row[logs_30s_key]
            if logs_per_second_30s_str and logs_per_second_30s_str != '':  # 檢查是否為空值
                logs_per_second_30s = float(logs_per_second_30s_str)
                if logs_per_second_30s > 6000:
                    # 添加正確的欄位鍵到row中，方便後續輸出
                    row['timestamp'] = row[timestamp_key]
                    row['logs_per_second_30s (每秒日誌數 (logs/s) - 30s 平均)'] = row[logs_30s_key]
                    high_throughput_data.append(row)
            else:
                # 如果logs_per_second_30s是空值，跳過該行
                continue
        except ValueError:
            # 如果無法轉換為浮點數，跳過該行
            skipped_rows += 1
            continue

# 顯示結果
print("時間戳記及 logs per second 30s 大於 6000 的資料:")
print("timestamp, logs_per_second_30s, logs_per_second_1m, requests_per_second, pg_inserts_per_second, redis_messages_per_second")
print("-" * 150)

for row in high_throughput_data:
    # 確保所有欄位都有值，否則提供預設值
    timestamp = row.get('timestamp', 'N/A')
    logs_per_second_30s = row.get('logs_per_second_30s (每秒日誌數 (logs/s) - 30s 平均)', 'N/A')
    logs_per_second_1m = row.get('logs_per_second_1m (每秒日誌數 (logs/s) - 1m 平滑)', 'N/A')
    requests_per_second = row.get('requests_per_second (每秒請求數 (req/s) - 批量請求)', 'N/A')
    pg_inserts_per_second = row.get('pg_inserts_per_second (PostgreSQL 每秒插入行數 (rows/s))', 'N/A')
    redis_messages_per_second = row.get('redis_messages_per_second (Redis Stream 每秒訊息數 (msg/s))', 'N/A')

    print(f"{timestamp}, {logs_per_second_30s}, {logs_per_second_1m}, {requests_per_second}, {pg_inserts_per_second}, {redis_messages_per_second}")

print(f"\n總共有 {len(high_throughput_data)} 筆資料符合條件 (logs per second 30s > 6000)")
print(f"共讀取了 {row_count} 行資料")
if skipped_rows > 0:
    print(f"跳過了 {skipped_rows} 行格式錯誤或缺少數據的資料")