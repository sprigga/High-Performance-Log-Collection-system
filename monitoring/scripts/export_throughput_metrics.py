#!/usr/bin/env python3
"""
系統吞吐量指標匯出工具

此腳本會查詢 Prometheus 中「系統吞吐量 (Throughput)」圖表的所有指標資料，
並將結果匯出為 CSV 檔案。

使用方式:
    python export_throughput_metrics.py --start "2024-11-25T00:00:00Z" --end "2024-11-25T23:59:59Z"
    或
    python export_throughput_metrics.py --duration 1h  # 最近 1 小時
    python export_throughput_metrics.py --duration 30m # 最近 30 分鐘
"""

import argparse
import csv
import sys
import os  # 新增: 用於檔案檢查
from datetime import datetime, timedelta
from typing import List, Dict, Any
import requests
from urllib.parse import urljoin
import pandas as pd  # 新增: 用於計算中位數和資料篩選
from pathlib import Path  # 新增: 用於路徑處理

# Prometheus 連線設定
PROMETHEUS_URL = "http://localhost:9090"


class PrometheusExporter:
    """Prometheus 指標查詢與匯出工具"""

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
            print(f"❌ 查詢失敗: {query}", file=sys.stderr)
            print(f"   錯誤: {e}", file=sys.stderr)
            return {"status": "error", "data": {"result": []}}

    def export_throughput_metrics(self, start: datetime, end: datetime, output_file: str = "throughput_metrics.csv"):
        """
        匯出系統吞吐量指標到 CSV

        這個方法會查詢 log-collection-dashboard.json 中「系統吞吐量 (Throughput)」
        面板定義的所有 4 個指標 (使用 irate[5s] 瞬時峰值):
        - 日誌數 (logs/s) - 瞬時峰值
        - Redis 訊息 (msg/s) - 瞬時峰值
        - PG 插入 (rows/s) - 瞬時峰值
        - HTTP 請求 (req/s) - 瞬時峰值
        """

        # 擴展時間範圍：開始時間往前推 1 分鐘，結束時間往後推 1 分鐘
        # 這樣可以確保擷取到完整的測試資料
        extended_start = start - timedelta(minutes=1)
        extended_end = end + timedelta(minutes=1)

        # 定義要查詢的指標 (核心效能比較指標)
        # 修改說明：統一主系統與對照組的查詢指標，確保一致性比較
        # 三大核心指標：1️⃣日誌吞吐量、2️⃣HTTP QPS、3️⃣PG插入速率
        queries = [
            {
                "name": "1_logs_throughput",
                "query": "sum(irate(logs_received_total[5s]))",
                "description": "1️⃣ 日誌吞吐量 (logs/s)"
            },
            {
                "name": "2_http_qps",
                "query": "sum(irate(http_requests_total[5s]))",
                "description": "2️⃣ HTTP QPS (req/s)"
            },
            {
                "name": "3_pg_insert_rate",
                "query": "sum(rate(pg_stat_database_tup_inserted{datname=\"logsdb\"}[30s]))",
                "description": "3️⃣ PG 插入速率 (rows/s)"
            },
            {
                "name": "redis_messages_per_second",
                "query": "sum(irate(redis_stream_messages_total{status='success'}[5s]))",
                "description": "Redis 訊息 (msg/s) - 主系統架構特有"
            }
        ]

        print(f"📊 開始查詢吞吐量指標...")
        print(f"   原始時間範圍: {start} ~ {end}")
        print(f"   擴展時間範圍: {extended_start} ~ {extended_end}")
        print(f"   (前後各擴展 1 分鐘以確保資料完整性)")
        print(f"   查詢指標數: {len(queries)}")
        print()

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

        print()

        # 如果沒有任何資料，提前結束
        if not timestamps:
            print("❌ 沒有任何資料可匯出")
            print("   請確認:")
            print("   1. Prometheus 服務是否正在運行 (http://localhost:9090)")
            print("   2. 時間範圍內是否有資料")
            print("   3. 指標名稱是否正確")
            return

        # 排序時間戳記
        sorted_timestamps = sorted(timestamps)

        # 準備輸出路徑 - 原始資料檔案
        # 使用絕對路徑來確保正確找到專案根目錄
        script_dir = Path(__file__).resolve().parent  # monitoring/scripts directory
        project_root = script_dir.parent.parent  # log-collection-system directory
        test_file_dir = project_root / "test_file"
        test_file_dir.mkdir(parents=True, exist_ok=True)

        original_output_file = str(test_file_dir / "monitoring_throughput_metrics.csv")

        # 寫入原始 CSV
        print(f"💾 寫入原始 CSV: {original_output_file}")
        with open(original_output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
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

        print(f"✅ 原始資料匯出完成!")
        print(f"   檔案: {original_output_file}")
        print(f"   資料筆數: {len(sorted_timestamps)}")
        print(f"   時間範圍: {sorted_timestamps[0]} ~ {sorted_timestamps[-1]}")
        print()

        # 篩選並匯出 HTTP QPS Top 20
        http_qps_data = all_data.get('2_http_qps', {}).get('data', {})
        if http_qps_data:
            print()
            print("🔍 開始進行 HTTP QPS Top 20 篩選...")

            # 排除零值、空值和null值，並按 HTTP QPS 降序排序
            # 建立 (timestamp, http_qps_value) 的列表
            valid_data = [
                (ts, v) for ts, v in http_qps_data.items()
                if v is not None and v != '' and v != 0
            ]

            if not valid_data:
                print("   ⚠️  所有 2_http_qps 資料都是零值/空值/null，無法進行篩選")
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

            # 匯出篩選後的資料到固定檔名
            filtered_output_file = str(test_file_dir / "monitoring_throughput_http_qps_top20.csv")
            print()
            print(f"💾 匯出篩選後 Top 20 資料: {filtered_output_file}")

            with open(filtered_output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
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

            print(f"✅ Top 20 資料匯出完成!")
            print(f"   檔案: {filtered_output_file}")
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
            print()
            print("⚠️  無法進行篩選: 2_http_qps 資料不存在")

    def filter_http_qps_top20(self, csv_file: str) -> str:
        """
        新增功能：篩選 HTTP QPS 欄位，排除 0、空值和 null，
        按照降序排序，取前 20 筆，匯出到固定檔名的 CSV

        Args:
            csv_file: 輸入的 CSV 檔案路徑

        Returns:
            輸出檔案路徑
        """
        print()
        print("=" * 70)
        print("  🔍 HTTP QPS Top 20 分析")
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
            from pathlib import Path
            # 使用絕對路徑來確保正確找到專案根目錄
            script_dir = Path(__file__).resolve().parent  # monitoring/scripts directory
            project_root = script_dir.parent.parent  # log-collection-system directory
            test_file_dir = project_root / "test_file"
            test_file_dir.mkdir(parents=True, exist_ok=True)

            output_file = str(test_file_dir / "http_qps_top20.csv")

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


def parse_duration(duration_str: str) -> timedelta:
    """
    解析時間長度字串

    Args:
        duration_str: 時間字串，如 "1h", "30m", "2d"

    Returns:
        timedelta 物件
    """
    unit = duration_str[-1]
    value = int(duration_str[:-1])

    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    else:
        raise ValueError(f"不支援的時間單位: {unit} (支援: s, m, h, d)")


def main():
    parser = argparse.ArgumentParser(
        description='匯出 Prometheus 系統吞吐量指標到 CSV',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  # 匯出最近 1 小時的資料
  %(prog)s --duration 1h

  # 匯出最近 30 分鐘的資料，指定輸出檔名
  %(prog)s --duration 30m --output my_metrics.csv

  # 匯出指定時間範圍的資料
  %(prog)s --start "2024-11-25T10:00:00" --end "2024-11-25T11:00:00"

  # 指定 Prometheus URL
  %(prog)s --duration 1h --prometheus http://prometheus:9090
        """
    )

    parser.add_argument(
        '--prometheus',
        default=PROMETHEUS_URL,
        help=f'Prometheus URL (預設: {PROMETHEUS_URL})'
    )

    parser.add_argument(
        '--duration',
        help='查詢時間長度 (例: 1h, 30m, 2d)。會從現在往前推算。'
    )

    parser.add_argument(
        '--start',
        help='開始時間 (ISO 格式，例: 2024-11-25T10:00:00)'
    )

    parser.add_argument(
        '--end',
        help='結束時間 (ISO 格式，例: 2024-11-25T11:00:00)'
    )

    parser.add_argument(
        '--output', '-o',
        default='throughput_metrics.csv',
        help='輸出 CSV 檔案名稱 (預設: throughput_metrics.csv)'
    )

    args = parser.parse_args()

    # 決定時間範圍
    if args.duration:
        # 使用相對時間
        end_time = datetime.now()
        duration = parse_duration(args.duration)
        start_time = end_time - duration
    elif args.start and args.end:
        # 使用絕對時間
        start_time = datetime.fromisoformat(args.start.replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(args.end.replace('Z', '+00:00'))
    else:
        # 預設: 最近 1 小時
        print("⚠️  未指定時間範圍，使用預設值: 最近 1 小時")
        print()
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=1)

    # 建立 exporter 並執行匯出
    exporter = PrometheusExporter(args.prometheus)
    exporter.export_throughput_metrics(start_time, end_time, args.output)

    # 修改：移除自動執行 HTTP QPS Top 20 分析（已改為直接在 export_throughput_metrics 中進行篩選並覆蓋原檔案）
    # 原程式碼（已註釋）：
    # if os.path.exists(args.output):
    #     try:
    #         exporter.filter_http_qps_top20(args.output)
    #     except Exception as e:
    #         print(f"\n⚠️  HTTP QPS Top 20 分析失敗: {e}")
    #         print("   主要匯出檔案不受影響")


if __name__ == "__main__":
    main()
