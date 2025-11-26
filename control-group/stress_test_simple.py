"""
對照組壓力測試腳本 - 測試簡化版系統
直接寫入 PostgreSQL，無負載平衡、連接池、Redis、Worker

整合功能：
- 壓力測試執行
- Prometheus 指標自動擷取與匯出
"""
import asyncio
import aiohttp
import time
import random
import csv
import requests
import os
import json  # 新增：JSON 匯出功能
from datetime import datetime, timedelta
from typing import List, Dict, Any
from urllib.parse import urljoin
from pathlib import Path

# ==========================================
# 測試配置
# ==========================================
BASE_URL = "http://localhost:18724"  # 對照組端點
NUM_DEVICES = 100                    # 設備數量
LOGS_PER_DEVICE = 100                # 每台設備發送的日誌數
CONCURRENT_LIMIT = 200               # 並發限制
BATCH_SIZE = 5                       # 批次大小
USE_BATCH_API = True                 # 是否使用批量 API
NUM_ITERATIONS = 50                 # 測試執行的循環次數
ITERATION_INTERVAL = 5               # 每次循環之間的間隔時間（秒）

# Prometheus 監控配置
PROMETHEUS_URL = "http://localhost:19090"  # 對照組 Prometheus 端點
EXPORT_METRICS = True                # 是否自動匯出指標

# 新增：Prometheus API 客戶端可用性檢查
try:
    from prometheus_api_client import PrometheusConnect
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print("⚠️  警告: prometheus_api_client 未安裝，Prometheus 指標查詢功能將被停用")

# 修改：使用相對路徑，動態計算專案根目錄下的 test_file/ 目錄
# 取得腳本所在目錄的父目錄（即專案根目錄）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_FILE_DIR = PROJECT_ROOT / "test_file"
METRICS_OUTPUT_FILE = str(TEST_FILE_DIR / "control_group_throughput_metrics.csv")

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LOG_MESSAGES = [
    "系統正常運行",
    "記憶體使用率: {usage}%",
    "CPU 溫度: {temp}°C",
    "網路連線異常",
    "資料庫查詢超時",
    "檔案讀取失敗",
    "感測器讀數異常",
    "攝影機畫面模糊",
    "硬碟空間不足",
    "設備重新啟動"
]

# ==========================================
# 新增：Prometheus 指標查詢器類別（整合自 query_prometheus_metrics.py）
# ==========================================
class PrometheusMetricsQuerier:
    """
    Prometheus 指標查詢器（整合自 query_prometheus_metrics.py）
    """
    def __init__(self, prometheus_url=PROMETHEUS_URL):
        """
        初始化 Prometheus 連接

        Args:
            prometheus_url (str): Prometheus 服務的 URL
        """
        if not PROMETHEUS_AVAILABLE:
            self.prometheus = None
            return

        try:
            self.prometheus = PrometheusConnect(url=prometheus_url, disable_ssl=True)
            self.prometheus_url = prometheus_url
        except Exception as e:
            print(f"⚠️  無法連接到 Prometheus: {e}")
            self.prometheus = None

    def test_connection(self):
        """測試與 Prometheus 的連接"""
        if not self.prometheus:
            return False

        try:
            # 嘗試獲取一個基本指標來測試連接
            result = self.prometheus.get_current_metric_value("up")
            return True
        except Exception as e:
            print(f"⚠️  無法連接到 Prometheus: {e}")
            return False

    def query_test_metrics(self, start_time, end_time, batch_size=BATCH_SIZE):
        """
        查詢測試期間的 Prometheus 指標

        Args:
            start_time (datetime): 測試開始時間
            end_time (datetime): 測試結束時間
            batch_size (int): 批次大小

        Returns:
            dict: 包含查詢結果的字典
        """
        if not self.prometheus:
            return {"error": "Prometheus 不可用"}

        metrics = {}

        try:
            # 獲取端點標籤名稱
            all_requests_result = self.prometheus.get_current_metric_value("http_requests_total")
            endpoint_label = 'endpoint'
            if all_requests_result:
                sample_labels = all_requests_result[0].get('metric', {})
                endpoint_label = 'endpoint' if 'endpoint' in sample_labels else 'handler' if 'handler' in sample_labels else 'endpoint'
        except:
            endpoint_label = 'endpoint'

        # 查詢時間範圍內的指標
        try:
            # QPS (所有端點)
            qps_result = self.prometheus.custom_query_range(
                query='rate(http_requests_total[1m])',
                start_time=start_time,
                end_time=end_time,
                step='1s'
            )

            # 計算最大和平均 QPS
            max_qps_values = []
            for result in qps_result:
                if 'values' in result:
                    values = [float(value[1]) for value in result['values'] if value[1] not in ['NaN', None]]
                    if values:
                        max_qps_values.extend(values)

            metrics['qps'] = {
                'max': max(max_qps_values, default=0) if max_qps_values else 0,
                'avg': sum(max_qps_values) / len(max_qps_values) if max_qps_values else 0
            }
        except Exception as e:
            print(f"⚠️  查詢 QPS 時發生錯誤: {e}")
            metrics['qps'] = {'max': 0, 'avg': 0}

        try:
            # 批量端點 QPS
            qps_batch_query = f'rate(http_requests_total{{{endpoint_label}="/api/logs/batch"}}[1m])'
            qps_batch_result = self.prometheus.custom_query_range(
                query=qps_batch_query,
                start_time=start_time,
                end_time=end_time,
                step='1s'
            )

            max_qps_batch_values = []
            for result in qps_batch_result:
                if 'values' in result:
                    values = [float(value[1]) for value in result['values'] if value[1] not in ['NaN', None]]
                    if values:
                        max_qps_batch_values.extend(values)

            metrics['qps_batch'] = {
                'max': max(max_qps_batch_values, default=0) if max_qps_batch_values else 0,
                'avg': sum(max_qps_batch_values) / len(max_qps_batch_values) if max_qps_batch_values else 0
            }
        except Exception as e:
            print(f"⚠️  查詢批量端點 QPS 時發生錯誤: {e}")
            metrics['qps_batch'] = {'max': 0, 'avg': 0}

        try:
            # 吞吐量 (Logs/s)
            throughput_query = f'rate(http_requests_total{{{endpoint_label}="/api/logs/batch"}}[1m]) * {batch_size}'
            throughput_result = self.prometheus.custom_query_range(
                query=throughput_query,
                start_time=start_time,
                end_time=end_time,
                step='1s'
            )

            max_throughput_values = []
            for result in throughput_result:
                if 'values' in result:
                    values = [float(value[1]) for value in result['values'] if value[1] not in ['NaN', None]]
                    if values:
                        max_throughput_values.extend(values)

            metrics['throughput'] = {
                'max': max(max_throughput_values, default=0) if max_throughput_values else 0,
                'avg': sum(max_throughput_values) / len(max_throughput_values) if max_throughput_values else 0
            }
        except Exception as e:
            print(f"⚠️  查詢吞吐量時發生錯誤: {e}")
            metrics['throughput'] = {'max': 0, 'avg': 0}

        try:
            # P95 響應時間
            p95_query = 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))'
            p95_result = self.prometheus.custom_query_range(
                query=p95_query,
                start_time=start_time,
                end_time=end_time,
                step='1s'
            )

            p95_values = []
            for result in p95_result:
                if 'values' in result:
                    values = [float(value[1]) * 1000 for value in result['values'] if value[1] not in ['NaN', None]]  # 轉換為 ms
                    if values:
                        p95_values.extend(values)

            metrics['p95_response_time'] = {
                'max': max(p95_values, default=0) if p95_values else 0,
                'avg': sum(p95_values) / len(p95_values) if p95_values else 0
            }
        except Exception as e:
            print(f"⚠️  查詢 P95 響應時間時發生錯誤: {e}")
            metrics['p95_response_time'] = {'max': 0, 'avg': 0}

        try:
            # P99 響應時間
            p99_query = 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))'
            p99_result = self.prometheus.custom_query_range(
                query=p99_query,
                start_time=start_time,
                end_time=end_time,
                step='1s'
            )

            p99_values = []
            for result in p99_result:
                if 'values' in result:
                    values = [float(value[1]) * 1000 for value in result['values'] if value[1] not in ['NaN', None]]  # 轉換為 ms
                    if values:
                        p99_values.extend(values)

            metrics['p99_response_time'] = {
                'max': max(p99_values, default=0) if p99_values else 0,
                'avg': sum(p99_values) / len(p99_values) if p99_values else 0
            }
        except Exception as e:
            print(f"⚠️  查詢 P99 響應時間時發生錯誤: {e}")
            metrics['p99_response_time'] = {'max': 0, 'avg': 0}

        try:
            # 錯誤率
            error_rate_query = 'rate(http_requests_total{status=~"5..|4.."}[1m])'
            error_rate_result = self.prometheus.custom_query_range(
                query=error_rate_query,
                start_time=start_time,
                end_time=end_time,
                step='1s'
            )

            error_rate_values = []
            for result in error_rate_result:
                if 'values' in result:
                    values = [float(value[1]) for value in result['values'] if value[1] not in ['NaN', None]]
                    if values:
                        error_rate_values.extend(values)

            metrics['error_rate'] = {
                'max': max(error_rate_values, default=0) if error_rate_values else 0,
                'avg': sum(error_rate_values) / len(error_rate_values) if error_rate_values else 0
            }
        except Exception as e:
            print(f"⚠️  查詢錯誤率時發生錯誤: {e}")
            metrics['error_rate'] = {'max': 0, 'avg': 0}

        return metrics

# ==========================================
# Prometheus 指標查詢與匯出
# ==========================================
class PrometheusExporter:
    """Prometheus 指標查詢與匯出工具（對照組版本）"""

    def __init__(self, prometheus_url: str = PROMETHEUS_URL):
        self.prometheus_url = prometheus_url
        self.query_url = urljoin(prometheus_url, "/api/v1/query_range")

    def query_range(self, query: str, start: datetime, end: datetime, step: str = "1s") -> Dict[str, Any]:
        """
        查詢 Prometheus 時間範圍資料

        Args:
            query: PromQL 查詢語句
            start: 開始時間
            end: 結束時間
            step: 時間間隔 (預設 1s)

        Returns:
            查詢結果 dict
        """
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step
        }

        try:
            response = requests.get(self.query_url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ 查詢失敗: {query}")
            print(f"   錯誤: {e}")
            return {"status": "error", "data": {"result": []}}

    def export_throughput_metrics(self, start: datetime, end: datetime, output_file: str = METRICS_OUTPUT_FILE):
        """
        匯出對照組系統吞吐量指標到 CSV

        這個方法會查詢 control-group-dashboard.json 中「系統吞吐量 (Throughput)」
        面板定義的 3 個指標 (使用 rate[30s] 平滑平均):
        - 日誌數 (logs/s) - 30s 平均
        - HTTP 請求 (req/s) - 30s 平均
        - PG 插入 (rows/s) - 30s 平均
        """

        # 修改：確保輸出目錄存在
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 擴展時間範圍：開始時間往前推 1 分鐘，結束時間往後推 1 分鐘
        # 這樣可以確保擷取到完整的測試資料
        extended_start = start - timedelta(minutes=1)
        extended_end = end + timedelta(minutes=1)

        # 定義要查詢的指標 (核心效能比較指標)
        # 修改說明：使用 rate[30s] 以確保能查詢到歷史數據
        # irate[5s] 僅適用於即時監控，無法查詢歷史時間範圍的數據
        # 三大核心指標：1️⃣日誌吞吐量、2️⃣HTTP QPS、3️⃣PG插入速率
        queries = [
            {
                "name": "1_logs_throughput",
                "query": "sum(rate(logs_received_total[30s]))",
                "description": "1️⃣ 日誌吞吐量 (logs/s)"
            },
            {
                "name": "2_http_qps",
                "query": "sum(rate(http_requests_total[30s]))",
                "description": "2️⃣ HTTP QPS (req/s)"
            },
            {
                "name": "3_pg_insert_rate",
                "query": "sum(rate(pg_stat_database_tup_inserted{datname=\"logsdb\"}[30s]))",
                "description": "3️⃣ PG 插入速率 (rows/s)"
            }
        ]

        print(f"\n📊 開始查詢對照組吞吐量指標...")
        print(f"   原始時間範圍: {start} ~ {end}")
        print(f"   擴展時間範圍: {extended_start} ~ {extended_end}")
        print(f"   (前後各擴展 1 分鐘以確保資料完整性)")
        print(f"   查詢指標數: {len(queries)}")

        # 查詢所有指標（使用擴展後的時間範圍）
        all_data = {}
        timestamps = set()

        for metric in queries:
            print(f"   查詢: {metric['description']}")
            result = self.query_range(
                metric['query'], extended_start, extended_end, step="1s"
            )

            if result.get("status") == "success" and result.get("data", {}).get("result"):
                # 取得第一個結果 (因為使用 sum() 聚合)
                values = result["data"]["result"][0].get("values", [])

                # 將資料存入 dict，以 timestamp 為 key
                metric_data = {}
                for ts, value in values:
                    timestamp = datetime.fromtimestamp(ts)
                    timestamps.add(timestamp)
                    metric_data[timestamp] = float(value)

                all_data[metric['name']] = {
                    'description': metric['description'],
                    'data': metric_data
                }
                print(f"      ✅ 取得 {len(values)} 筆資料")
            else:
                print(f"      ⚠️  無資料或查詢失敗")
                all_data[metric['name']] = {
                    'description': metric['description'],
                    'data': {}
                }

        # 如果沒有任何資料，提前結束
        if not timestamps:
            print("❌ 沒有任何資料可匯出")
            print("   請確認:")
            print(f"   1. Prometheus 服務是否正在運行 ({self.prometheus_url})")
            print("   2. 時間範圍內是否有資料")
            print("   3. 指標名稱是否正確")
            return

        # 排序時間戳記
        sorted_timestamps = sorted(timestamps)

        # 寫入 CSV
        print(f"\n💾 寫入 CSV: {output_file}")
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
            # 準備欄位名稱
            fieldnames = ['timestamp'] + [
                f"{metric['name']} ({metric['description']})"
                for metric in queries
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            # 寫入資料
            for ts in sorted_timestamps:
                row = {'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S')}

                for metric in queries:
                    metric_name = metric['name']
                    column_name = f"{metric_name} ({metric['description']})"

                    # 取得該時間點的值，如果沒有則留空
                    value = all_data[metric_name]['data'].get(ts, '')
                    row[column_name] = value

                writer.writerow(row)

        print(f"✅ 匯出完成!")
        print(f"   檔案: {output_file}")
        print(f"   資料筆數: {len(sorted_timestamps)}")
        print(f"   時間範圍: {sorted_timestamps[0]} ~ {sorted_timestamps[-1]}")
        print()
        print("📈 統計摘要:")
        for metric in queries:
            metric_name = metric['name']
            data_values = list(all_data[metric_name]['data'].values())
            if data_values:
                print(f"   {metric['description']}:")
                print(f"      最大值: {max(data_values):.2f}")
                print(f"      最小值: {min(data_values):.2f}")
                print(f"      平均值: {sum(data_values)/len(data_values):.2f}")
        # 修改：使用 HTTP QPS (2_http_qps) 欄位篩選並取前 20 筆
        # 原程式碼（已註釋）：使用中位數篩選
        import pandas as pd

        http_qps_data = all_data.get('2_http_qps', {}).get('data', {})
        if http_qps_data:
            print()
            print("🔍 開始進行 HTTP QPS Top 20 篩選...")

            # 排除零值、空值和null值，並按 HTTP QPS 降序排序
            # 建立 (timestamp, http_qps_value) 的列表
            valid_data = [
                (ts, v) for ts, v in http_qps_data.items()
                if v is not None and v != '' and v > 0
            ]

            if not valid_data:
                print("   ⚠️  所有 2_http_qps 資料都是零值/空值/null，無法進行篩選")
                print()
                print("⚠️  無法進行篩選: 沒有有效的 2_http_qps 資料")
                return

            # 使用 pandas 排序並取前 20 筆
            df_temp = pd.DataFrame(valid_data, columns=['timestamp', 'http_qps'])
            df_sorted = df_temp.sort_values(by='http_qps', ascending=False)
            df_top20 = df_sorted.head(20)

            print(f"   原始資料筆數: {len(http_qps_data)}")
            print(f"   非零資料筆數: {len(valid_data)}")
            print(f"   篩選後筆數: {len(df_top20)}")
            print(f"   HTTP QPS 範圍: {df_top20['http_qps'].min():.2f} ~ {df_top20['http_qps'].max():.2f}")

            # 取得前 20 筆的時間戳記
            filtered_timestamps = df_top20['timestamp'].tolist()
            # 按時間排序（方便閱讀）
            filtered_timestamps.sort()

            # 修改：匯出到固定檔名，不含日期時間
            top20_output_file = str(TEST_FILE_DIR / "control_group_http_qps_top20.csv")
            print()
            print(f"💾 匯出 Top 20 資料到固定檔名: {top20_output_file}")

            with open(top20_output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
                # 準備欄位名稱 (與原始檔案相同)
                fieldnames = ['timestamp'] + [
                    f"{metric['name']} ({metric['description']})"
                    for metric in queries
                ]

                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

                # 寫入篩選後的資料
                for ts in filtered_timestamps:
                    row = {'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S')}

                    for metric in queries:
                        metric_name = metric['name']
                        column_name = f"{metric_name} ({metric['description']})"

                        # 取得該時間點的值，如果沒有則留空
                        value = all_data[metric_name]['data'].get(ts, '')
                        row[column_name] = value

                    writer.writerow(row)

            print(f"✅ Top 20 資料已匯出到固定檔案!")
            print(f"   檔案: {top20_output_file}")
            print(f"   資料筆數: {len(filtered_timestamps)}")
            if filtered_timestamps:
                print(f"   時間範圍: {filtered_timestamps[0]} ~ {filtered_timestamps[-1]}")

            # 顯示篩選後的統計摘要
            print()
            print("📊 Top 20 統計摘要:")
            for metric in queries:
                metric_name = metric['name']
                # 只取篩選後時間戳記的資料
                filtered_metric_values = [
                    all_data[metric_name]['data'].get(ts, 0)
                    for ts in filtered_timestamps
                    if all_data[metric_name]['data'].get(ts) is not None
                ]

                if filtered_metric_values:
                    print(f"   {metric['description']}:")
                    print(f"      平均值: {sum(filtered_metric_values)/len(filtered_metric_values):.2f}")
                    print(f"      最大值: {max(filtered_metric_values):.2f}")
                    print(f"      最小值: {min(filtered_metric_values):.2f}")
        else:
                        print("⚠️  無法進行篩選: 2_http_qps 資料不存在")

    def filter_logs_per_second_by_median(self, csv_file: str, output_file: str = None):
        """
        使用 pandas 對 CSV 文件中的 'logs per second' 欄位進行低偏差值篩選
        篩選條件：先排除 0、空值、null 值，然後以大於中位數的數據進行篩選
        篩選後計算平均值

        Args:
            csv_file: 輸入的 CSV 檔案路徑
            output_file: 輸出的 CSV 檔案路徑（可選，預設為原檔案名加上 '_filtered'）
        """
        import pandas as pd

        if output_file is None:
            # 生成輸出檔名：原檔名 + '_filtered'
            import os
            base_name = os.path.splitext(csv_file)[0]
            extension = os.path.splitext(csv_file)[1]
            output_file = f"{base_name}_filtered{extension}"

        try:
            # 讀取 CSV 文件
            print(f"\n📊 使用 pandas 進行低偏差值篩選分析...")
            print(f"   讀取檔案: {csv_file}")

            df = pd.read_csv(csv_file)
            print(f"   原始資料筆數: {len(df)}")

            # 尋找包含 "logs" 和 "per" 和 "second" 的欄位
            logs_column = None
            for col in df.columns:
                if 'logs' in col.lower() and 'per' in col.lower() and 'second' in col.lower():
                    logs_column = col
                    break

            if logs_column is None:
                print("❌ 找不到包含 'logs per second' 的欄位")
                print(f"   可用欄位: {list(df.columns)}")
                return None

            print(f"   目標欄位: '{logs_column}'")

            # 修改：先移除 NaN 值、空值和非數值資料
            original_count = len(df)
            df_clean = df[pd.notna(df[logs_column]) & (df[logs_column] != '')]

            # 確保該欄位為數值型態
            df_clean.loc[:, logs_column] = pd.to_numeric(df_clean[logs_column], errors='coerce')
            df_clean = df_clean.dropna(subset=[logs_column])

            # 修改：再移除 0 值
            df_clean = df_clean[df_clean[logs_column] > 0]

            print(f"   清理後資料筆數: {len(df_clean)} (移除 {original_count - len(df_clean)} 筆無效資料，包含 0、空值、null)")
            # print(f"   清理後資料筆數: {len(df_clean)} (移除 {original_count - len(df_clean)} 筆無效資料)")

            if len(df_clean) == 0:
                print("❌ 清理後沒有有效資料")
                return None

            # 計算統計數據
            logs_data = df_clean[logs_column]

            print(f"\n📈 '{logs_column}' 統計分析 (已排除 0、空值、null):")
            # print(f"\n📈 '{logs_column}' 統計分析:")
            print(f"   平均值: {logs_data.mean():.2f}")
            print(f"   中位數: {logs_data.median():.2f}")
            print(f"   標準差: {logs_data.std():.2f}")
            print(f"   最小值: {logs_data.min():.2f}")
            print(f"   最大值: {logs_data.max():.2f}")
            # print(f"   非零值數量: {(logs_data > 0).sum()}")
            # print(f"   零值數量: {(logs_data == 0).sum()}")
            print(f"   有效值數量: {len(logs_data)}")

            # 計算中位數
            median_value = logs_data.median()
            print(f"\n🎯 篩選條件: > {median_value:.2f} (中位數)")

            # 進行篩選：大於中位數的資料
            filtered_df = df_clean[df_clean[logs_column] > median_value].copy()

            print(f"   篩選前資料筆數: {len(df_clean)}")
            print(f"   篩選後資料筆數: {len(filtered_df)}")
            print(f"   保留比例: {len(filtered_df)/len(df_clean)*100:.1f}%")

            if len(filtered_df) == 0:
                print("⚠️  篩選後沒有資料（所有值都小於等於中位數）")
                return None

            # 計算篩選後的統計數據
            filtered_logs_data = filtered_df[logs_column]

            print(f"\n📊 篩選後統計:")
            print(f"   平均值: {filtered_logs_data.mean():.2f}")
            print(f"   中位數: {filtered_logs_data.median():.2f}")
            print(f"   標準差: {filtered_logs_data.std():.2f}")
            print(f"   最小值: {filtered_logs_data.min():.2f}")
            print(f"   最大值: {filtered_logs_data.max():.2f}")

            # 與原始數據比較
            print(f"\n📈 篩選效果:")
            print(f"   平均值變化: {logs_data.mean():.2f} → {filtered_logs_data.mean():.2f} (提升 {(filtered_logs_data.mean()-logs_data.mean())/logs_data.mean()*100:.1f}%)")
            print(f"   標準差變化: {logs_data.std():.2f} → {filtered_logs_data.std():.2f}")

            # 計算變異係數改善
            original_cv = logs_data.std() / logs_data.mean() if logs_data.mean() > 0 else 0
            filtered_cv = filtered_logs_data.std() / filtered_logs_data.mean() if filtered_logs_data.mean() > 0 else 0
            print(f"   變異係數: {original_cv:.3f} → {filtered_cv:.3f}")

            # 儲存篩選後的資料
            print(f"\n💾 儲存篩選後資料...")
            print(f"   輸出檔案: {output_file}")

            filtered_df.to_csv(output_file, index=False, encoding='utf-8-sig')

            print(f"✅ 篩選完成!")
            print(f"   原始資料: {len(df_clean)} 筆")
            print(f"   篩選後: {len(filtered_df)} 筆 (保留 {len(filtered_df)/len(df_clean)*100:.1f}%)")
            print(f"   篩選後平均值: {filtered_logs_data.mean():.2f}")

            return {
                'original_count': len(df_clean),
                'filtered_count': len(filtered_df),
                'original_mean': logs_data.mean(),
                'filtered_mean': filtered_logs_data.mean(),
                'median_threshold': median_value,
                'output_file': output_file
            }

        except ImportError:
            print("❌ pandas 套件未安裝")
            print("   請執行: pip install pandas")
            return None
        except FileNotFoundError:
            print(f"❌ 檔案不存在: {csv_file}")
            return None
        except Exception as e:
            print(f"❌ 篩選過程發生錯誤: {e}")
            return None

    def filter_http_qps_top20(self, csv_file: str) -> str:
        """
        新增功能：篩選 HTTP QPS 欄位，排除 0、空值和 null，
        按照降序排序，取前 20 筆，匯出到固定檔名的 CSV

        Args:
            csv_file: 輸入的 CSV 檔案路徑

        Returns:
            輸出檔案路徑
        """
        import pandas as pd

        print()
        print("=" * 70)
        print("  🔍 對照組 HTTP QPS Top 20 分析")
        print("=" * 70)
        print(f"   讀取檔案: {csv_file}")

        try:
            # 讀取 CSV
            df = pd.read_csv(csv_file)
            print(f"   原始資料筆數: {len(df)}")

            # 尋找 HTTP QPS 欄位
            http_qps_column = None
            for col in df.columns:
                if '2_http_qps' in col:
                    http_qps_column = col
                    break

            if http_qps_column is None:
                print("❌ 找不到 '2_http_qps' 欄位")
                print(f"   可用欄位: {list(df.columns)}")
                return None

            print(f"   目標欄位: '{http_qps_column}'")

            # 篩選掉 0、空值和 null
            df_clean = df.copy()
            df_clean = df_clean[pd.notna(df_clean[http_qps_column]) & (df_clean[http_qps_column] != '')]
            df_clean.loc[:, http_qps_column] = pd.to_numeric(df_clean[http_qps_column], errors='coerce')
            df_clean = df_clean.dropna(subset=[http_qps_column])
            df_clean = df_clean[df_clean[http_qps_column] > 0]

            print(f"   篩選後資料筆數: {len(df_clean)} (移除了 {len(df) - len(df_clean)} 筆無效資料)")

            if len(df_clean) == 0:
                print("❌ 篩選後沒有有效資料")
                return None

            # 降序排序並取前 20 筆
            df_sorted = df_clean.sort_values(by=http_qps_column, ascending=False)
            df_top20 = df_sorted.head(20)

            print(f"   取得前 20 筆資料")

            # 確定輸出檔案路徑（固定檔名，放在 test_file/ 目錄）
            test_file_dir = TEST_FILE_DIR
            output_file = str(test_file_dir / "control_group_http_qps_top20.csv")

            # 匯出 CSV
            df_top20.to_csv(output_file, index=False, encoding='utf-8-sig')

            print()
            print(f"✅ 匯出完成!")
            print(f"   輸出檔案: {output_file}")
            print(f"   資料筆數: {len(df_top20)}")
            print()
            print("📊 Top 20 統計摘要:")
            print(f"   最大值: {df_top20[http_qps_column].max():.2f}")
            print(f"   最小值: {df_top20[http_qps_column].min():.2f}")
            print(f"   平均值: {df_top20[http_qps_column].mean():.2f}")
            print(f"   中位數: {df_top20[http_qps_column].median():.2f}")
            print("=" * 70)

            return output_file

        except Exception as e:
            print(f"❌ 處理失敗: {e}")
            import traceback
            traceback.print_exc()
            return None

# ==========================================
# 生成測試資料
# ==========================================
def generate_log_data(device_id: str, log_num: int) -> dict:
    """生成隨機日誌資料"""
    log_level = random.choice(LOG_LEVELS)
    message_template = random.choice(LOG_MESSAGES)

    if "{usage}" in message_template:
        message = message_template.format(usage=random.randint(50, 95))
    elif "{temp}" in message_template:
        message = message_template.format(temp=random.randint(40, 85))
    else:
        message = message_template

    return {
        "device_id": device_id,
        "log_level": log_level,
        "message": f"{message} (#{log_num})",
        "log_data": {
            "test_id": log_num,
            "timestamp": datetime.now().isoformat(),
            "random_value": random.random(),
            "sequence": log_num
        }
    }

# ==========================================
# 發送單筆日誌
# ==========================================
async def send_log(session: aiohttp.ClientSession, device_id: str, log_num: int) -> dict:
    """發送單筆日誌到 API"""
    url = f"{BASE_URL}/api/log"
    log_data = generate_log_data(device_id, log_num)

    start_time = time.time()

    try:
        async with session.post(url, json=log_data, timeout=aiohttp.ClientTimeout(total=30)) as response:
            response_time = (time.time() - start_time) * 1000

            if response.status == 200:
                return {
                    "success": True,
                    "response_time": response_time,
                    "status": response.status,
                    "error": None,
                    "count": 1
                }
            else:
                return {
                    "success": False,
                    "response_time": response_time,
                    "status": response.status,
                    "error": await response.text(),
                    "count": 1
                }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "response_time": (time.time() - start_time) * 1000,
            "status": 0,
            "error": "請求超時",
            "count": 1
        }
    except Exception as e:
        return {
            "success": False,
            "response_time": (time.time() - start_time) * 1000,
            "status": 0,
            "error": str(e),
            "count": 1
        }

# ==========================================
# 發送批量日誌
# ==========================================
async def send_batch_logs(session: aiohttp.ClientSession, logs: List[dict]) -> dict:
    """批量發送日誌到 API"""
    url = f"{BASE_URL}/api/logs/batch"
    batch_data = {"logs": logs}

    start_time = time.time()

    try:
        async with session.post(url, json=batch_data, timeout=aiohttp.ClientTimeout(total=60)) as response:
            response_time = (time.time() - start_time) * 1000

            if response.status == 200:
                return {
                    "success": True,
                    "response_time": response_time,
                    "status": response.status,
                    "error": None,
                    "count": len(logs)
                }
            else:
                return {
                    "success": False,
                    "response_time": response_time,
                    "status": response.status,
                    "error": await response.text(),
                    "count": len(logs)
                }

    except asyncio.TimeoutError:
        return {
            "success": False,
            "response_time": (time.time() - start_time) * 1000,
            "status": 0,
            "error": "請求超時",
            "count": len(logs)
        }
    except Exception as e:
        return {
            "success": False,
            "response_time": (time.time() - start_time) * 1000,
            "status": 0,
            "error": str(e),
            "count": len(logs)
        }

# ==========================================
# 批次發送日誌
# ==========================================
async def batch_send_logs(
    session: aiohttp.ClientSession,
    device_id: str,
    num_logs: int,
    semaphore: asyncio.Semaphore
) -> List[dict]:
    """批次發送日誌（使用信號量控制並發）"""
    if USE_BATCH_API:
        all_logs = [generate_log_data(device_id, log_num) for log_num in range(num_logs)]
        results = []

        for i in range(0, len(all_logs), BATCH_SIZE):
            batch = all_logs[i:i + BATCH_SIZE]
            async with semaphore:
                result = await send_batch_logs(session, batch)
                results.append(result)

        return results
    else:
        async def send_with_semaphore(log_num: int) -> dict:
            async with semaphore:
                return await send_log(session, device_id, log_num)

        tasks = [send_with_semaphore(log_num) for log_num in range(num_logs)]
        return await asyncio.gather(*tasks)

# ==========================================
# 主要壓力測試
# ==========================================
async def stress_test(
    num_devices: int = NUM_DEVICES,
    logs_per_device: int = LOGS_PER_DEVICE,
    concurrent_limit: int = CONCURRENT_LIMIT,
    iteration: int = 1,
    current_iteration: int = 1
):
    """執行壓力測試"""
    print("=" * 70)
    if iteration > 1:
        print(f"  📊 對照組 - 簡化系統壓力測試 [第 {current_iteration}/{iteration} 輪]")
    else:
        print("  📊 對照組 - 簡化系統壓力測試")
    print("=" * 70)
    print(f"測試配置：")
    print(f"  • 設備數量: {num_devices}")
    print(f"  • 每台設備日誌數: {logs_per_device}")
    print(f"  • 總日誌數: {num_devices * logs_per_device:,}")
    print(f"  • 並發限制: {concurrent_limit}")
    print(f"  • API 端點: {BASE_URL}")
    print(f"  • 系統特性: 無 Nginx、連接池、Redis、Worker")
    if iteration > 1:
        print(f"  • 總循環次數: {iteration}")
        print(f"  • 當前循環: {current_iteration}")
    print("-" * 70)

    semaphore = asyncio.Semaphore(concurrent_limit)

    # 記錄測試開始時間（用於 Prometheus 查詢）
    test_start_datetime = datetime.now()
    start_time = time.time()

    connector = aiohttp.TCPConnector(limit=concurrent_limit, limit_per_host=concurrent_limit)
    timeout = aiohttp.ClientTimeout(total=600)  # 10分鐘超時（簡化版較慢）

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        device_tasks = []

        for device_num in range(num_devices):
            # 修改：加入 'control_' 前綴以區分對照組測試資料
            device_id = f"control_device_{device_num:03d}"
            task = batch_send_logs(session, device_id, logs_per_device, semaphore)
            device_tasks.append(task)

        print("⏳ 開始發送日誌...")
        all_results = await asyncio.gather(*device_tasks)

    total_time = time.time() - start_time
    # 記錄測試結束時間（用於 Prometheus 查詢）
    test_end_datetime = datetime.now()

    # 整理結果
    all_responses = [result for device_results in all_results for result in device_results]

    total_requests = len(all_responses)
    successful_requests = sum(1 for r in all_responses if r["success"])
    failed_requests = total_requests - successful_requests
    total_logs_sent = sum(r.get("count", 1) for r in all_responses)
    successful_logs = sum(r.get("count", 1) for r in all_responses if r["success"])

    response_times = [r["response_time"] for r in all_responses if r["success"]]

    if response_times:
        avg_response_time = sum(response_times) / len(response_times)
        min_response_time = min(response_times)
        max_response_time = max(response_times)

        sorted_times = sorted(response_times)
        p50 = sorted_times[int(len(sorted_times) * 0.50)]
        p95 = sorted_times[int(len(sorted_times) * 0.95)]
        p99 = sorted_times[int(len(sorted_times) * 0.99)]
    else:
        avg_response_time = 0
        min_response_time = 0
        max_response_time = 0
        p50 = p95 = p99 = 0

    throughput = successful_logs / total_time if total_time > 0 else 0

    # 計算 QPS（請求數/秒）
    qps = successful_requests / total_time if total_time > 0 else 0

    # 輸出結果
    print("\n" + "=" * 70)
    print("  📈 測試結果")
    print("=" * 70)

    print(f"\n⏱️  時間統計：")
    print(f"  • 總耗時: {total_time:.2f} 秒")

    print(f"\n📊 請求統計：")
    if USE_BATCH_API:
        print(f"  • 批量請求數: {total_requests:,}")
        print(f"  • 總日誌數: {total_logs_sent:,}")
        print(f"  • 成功日誌: {successful_logs:,} ({successful_logs/total_logs_sent*100:.1f}%)")
    else:
        print(f"  • 總請求數: {total_requests:,}")
    print(f"  • 成功請求: {successful_requests:,} ({successful_requests/total_requests*100:.1f}%)")
    print(f"  • 失敗請求: {failed_requests:,} ({failed_requests/total_requests*100:.1f}%)")

    print(f"\n⚡ 效能指標：")
    print(f"  • QPS: {qps:.2f} req/秒")
    print(f"  • 吞吐量: {throughput:.2f} logs/秒")
    print(f"  • 平均回應時間: {avg_response_time:.2f} ms")
    print(f"  • 最小回應時間: {min_response_time:.2f} ms")
    print(f"  • 最大回應時間: {max_response_time:.2f} ms")

    print(f"\n📉 百分位數：")
    print(f"  • P50 (中位數): {p50:.2f} ms")
    print(f"  • P95: {p95:.2f} ms")
    print(f"  • P99: {p99:.2f} ms")

    # 錯誤分析（用於 JSON 匯出和控制台顯示）
    error_types = {}
    if failed_requests > 0:
        print(f"\n❌ 錯誤分析：")
        for r in all_responses:
            if not r["success"]:
                error = r["error"] or f"HTTP {r['status']}"
                error_types[error] = error_types.get(error, 0) + 1

        for error, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
            print(f"  • {error}: {count} 次")

    print("\n" + "=" * 70)

    target_throughput = 10000
    target_p95 = 100

    print(f"\n🎯 目標達成情況：")

    if throughput >= target_throughput:
        print(f"  ✅ 吞吐量達標: {throughput:.2f} >= {target_throughput} logs/秒")
    else:
        print(f"  ❌ 吞吐量未達標: {throughput:.2f} < {target_throughput} logs/秒")

    if p95 <= target_p95:
        print(f"  ✅ P95 回應時間達標: {p95:.2f} <= {target_p95} ms")
    else:
        print(f"  ❌ P95 回應時間未達標: {p95:.2f} > {target_p95} ms")

    if failed_requests == 0:
        print(f"  ✅ 無失敗請求")
    else:
        print(f"  ⚠️ 有 {failed_requests} 個失敗請求")

    print("=" * 70)

    # ==========================================
    # 匯出 Prometheus 指標
    # ==========================================
    # 修改：只在最後一輪測試完成時才匯出指標（整合所有測試數據）
    # if EXPORT_METRICS:
    #     try:
    #         print("\n" + "=" * 70)
    #         print("  📊 匯出 Prometheus 吞吐量指標")
    #         print("=" * 70)
    #
    #         exporter = PrometheusExporter(PROMETHEUS_URL)
    #
    #         # 為每個循環生成唯一的檔案名稱
    #         if iteration > 1:
    #             output_file = f"control_group_throughput_metrics_iter{current_iteration:02d}.csv"
    #         else:
    #             output_file = METRICS_OUTPUT_FILE
    #
    #         exporter.export_throughput_metrics(
    #             test_start_datetime,
    #             test_end_datetime,
    #             output_file
    #         )
    #
    #         print("=" * 70)
    #     except Exception as e:
    #         print(f"\n⚠️  指標匯出失敗: {e}")
    #         print("   測試結果不受影響，可手動匯出指標")

    # 修改：返回完整測試結果供 JSON 匯出使用（參考 tests/stress_test.py）
    return {
        "iteration": current_iteration,
        "total_iterations": iteration,
        "timestamp": datetime.now().isoformat(),
        "test_time_range": {
            "start": test_start_datetime.isoformat(),
            "end": test_end_datetime.isoformat()
        },
        "config": {
            "num_devices": num_devices,
            "logs_per_device": logs_per_device,
            "total_logs": num_devices * logs_per_device,
            "concurrent_limit": concurrent_limit,
            "batch_size": BATCH_SIZE,
            "use_batch_api": USE_BATCH_API,
            "base_url": BASE_URL
        },
        "timing": {
            "total_time": round(total_time, 2),
        },
        "requests": {
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "success_rate": round(successful_requests/total_requests*100, 2) if total_requests > 0 else 0
        },
        "logs": {
            "total_logs_sent": total_logs_sent,
            "successful_logs": successful_logs,
            "success_rate": round(successful_logs/total_logs_sent*100, 2) if total_logs_sent > 0 else 0
        },
        "performance": {
            "qps": round(qps, 2),
            "throughput": round(throughput, 2),
            "avg_response_time": round(avg_response_time, 2),
            "min_response_time": round(min_response_time, 2),
            "max_response_time": round(max_response_time, 2)
        },
        "percentiles": {
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2)
        },
        "errors": error_types,
        "targets": {
            "throughput": {
                "target": target_throughput,
                "actual": round(throughput, 2),
                "achieved": throughput >= target_throughput
            },
            "p95_response_time": {
                "target": target_p95,
                "actual": round(p95, 2),
                "achieved": p95 <= target_p95
            },
            "zero_failures": {
                "achieved": failed_requests == 0,
                "failed_count": failed_requests
            }
        }
    }

# ==========================================
# 主程式
# ==========================================
async def main():
    """主程式入口"""
    # 記錄整體測試開始時間（用於匯出指標和 JSON）
    overall_start_time = datetime.now()

    # 修改：記錄所有測試的時間範圍（用於 Prometheus 指標匯出）
    all_test_start = None
    all_test_end = None

    # 新增：收集所有測試結果（用於 JSON 匯出）
    all_test_results = []

    for i in range(NUM_ITERATIONS):
        # 修改：接收測試結果字典而非時間元組
        result = await stress_test(
            num_devices=NUM_DEVICES,
            logs_per_device=LOGS_PER_DEVICE,
            concurrent_limit=CONCURRENT_LIMIT,
            iteration=NUM_ITERATIONS,
            current_iteration=i + 1
        )

        # 收集測試結果
        all_test_results.append(result)

        # 從結果中提取時間範圍用於 Prometheus 匯出
        test_start = datetime.fromisoformat(result["test_time_range"]["start"])
        test_end = datetime.fromisoformat(result["test_time_range"]["end"])

        # 記錄第一次測試的開始時間
        if all_test_start is None:
            all_test_start = test_start

        # 更新最後一次測試的結束時間
        all_test_end = test_end

        # 簡單顯示進度
        print(f"✅ 第 {i + 1}/{NUM_ITERATIONS} 輪測試完成")

        if i < NUM_ITERATIONS - 1 and ITERATION_INTERVAL > 0:
            print(f"\n⏸️  等待 {ITERATION_INTERVAL} 秒後開始下一輪測試...")
            await asyncio.sleep(ITERATION_INTERVAL)

    # 記錄整體測試結束時間
    overall_end_time = datetime.now()

    # ==========================================
    # 新增：查詢 Prometheus 指標（參考 tests/stress_test.py）
    # ==========================================
    print("\n" + "=" * 70)
    print("⏳ 等待 10 秒讓 Prometheus 收集完整指標...")
    print("=" * 70)
    await asyncio.sleep(10)

    # 修改：所有測試完成後，匯出整合的 Prometheus 指標到單一 CSV 檔案
    if EXPORT_METRICS and all_test_start and all_test_end:
        try:
            print("\n" + "=" * 70)
            print("  📊 匯出所有測試的 Prometheus 吞吐量指標（整合版）")
            print("=" * 70)
            print(f"  • 測試輪數: {NUM_ITERATIONS}")
            print(f"  • 總時間範圍: {all_test_start} ~ {all_test_end}")
            print(f"  • 輸出檔案: {METRICS_OUTPUT_FILE}")
            print("=" * 70)

            exporter = PrometheusExporter(PROMETHEUS_URL)
            exporter.export_throughput_metrics(
                all_test_start,
                all_test_end,
                METRICS_OUTPUT_FILE
            )

            print("=" * 70)
        except Exception as e:
            print(f"\n⚠️  指標匯出失敗: {e}")
            print("   測試結果不受影響，可手動匯出指標")


    # ==========================================
    # 新增：匯出所有測試結果為 JSON（包含 Prometheus 指標）
    # ==========================================
    print("\n" + "=" * 70)
    print("  📄 匯出對照組測試結果")
    print("=" * 70)

    # 確保輸出目錄存在
    TEST_FILE_DIR.mkdir(parents=True, exist_ok=True)

    # 產生輸出檔案名稱（使用時間戳記）
    timestamp_str = overall_start_time.strftime("%Y%m%d_%H%M%S")
    output_file = TEST_FILE_DIR / f"control_group_stress_test_results_{timestamp_str}.json"

    # 準備完整的測試報告
    test_report = {
        "test_summary": {
            "test_type": "control_group",
            "start_time": overall_start_time.isoformat(),
            "end_time": overall_end_time.isoformat(),
            "total_duration": round((overall_end_time - overall_start_time).total_seconds(), 2),
            "num_iterations": NUM_ITERATIONS,
            "iteration_interval": ITERATION_INTERVAL
        },
        "iterations": all_test_results
    }

    # 匯出 JSON
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(test_report, f, ensure_ascii=False, indent=2)

        print(f"✅ 測試結果已匯出至: {output_file}")
        print(f"   包含 {len(all_test_results)} 輪測試結果")
        print("=" * 70)
    except Exception as e:
        print(f"❌ 匯出測試結果時發生錯誤: {e}")
        print("=" * 70)

    # 修改：移除低偏差值篩選和 HTTP QPS Top 20 分析（已改為在 export_throughput_metrics 中直接進行篩選並覆蓋原檔案）
    # 原程式碼（已註釋）：
    # ==========================================
    # 執行低偏差值篩選
    # ==========================================
    # if EXPORT_METRICS and os.path.exists(METRICS_OUTPUT_FILE):
    #     try:
    #         print("\n" + "=" * 70)
    #         print("  🔍 執行低偏差值篩選（基於 logs per second 中位數）")
    #         print("=" * 70)
    #
    #         exporter = PrometheusExporter(PROMETHEUS_URL)
    #         filter_result = exporter.filter_logs_per_second_by_median(METRICS_OUTPUT_FILE)
    #
    #         if filter_result:
    #             print("\n📈 篩選結果摘要:")
    #             print(f"  • 原始資料筆數: {filter_result['original_count']}")
    #             print(f"  • 篩選後筆數: {filter_result['filtered_count']}")
    #             print(f"  • 保留比例: {filter_result['filtered_count']/filter_result['original_count']*100:.1f}%")
    #             print(f"  • 篩選閾值 (中位數): {filter_result['median_threshold']:.2f}")
    #             print(f"  • 原始平均值: {filter_result['original_mean']:.2f}")
    #             print(f"  • 篩選後平均值: {filter_result['filtered_mean']:.2f}")
    #             print(f"  • 平均值提升: {(filter_result['filtered_mean']-filter_result['original_mean'])/filter_result['original_mean']*100:.1f}%")
    #             print(f"  • 篩選後檔案: {filter_result['output_file']}")
    #
    #         print("=" * 70)
    #     except Exception as e:
    #         print(f"\n⚠️  低偏差值篩選失敗: {e}")
    #         print("   請確認 pandas 已安裝: pip install pandas")
    #
    # ==========================================
    # 新增功能：執行 HTTP QPS Top 20 分析
    # ==========================================
    # 修改說明：匯出完成後，自動進行 HTTP QPS Top 20 分析
    # if EXPORT_METRICS and os.path.exists(METRICS_OUTPUT_FILE):
    #     try:
    #         exporter = PrometheusExporter(PROMETHEUS_URL)
    #         exporter.filter_http_qps_top20(METRICS_OUTPUT_FILE)
    #     except Exception as e:
    #         print(f"\n⚠️  HTTP QPS Top 20 分析失敗: {e}")
    #         print("   主要匯出檔案不受影響")

    print("\n✅ 測試完成")

if __name__ == "__main__":
    asyncio.run(main())
