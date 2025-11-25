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
from datetime import datetime, timedelta
from typing import List, Dict, Any
import requests
from urllib.parse import urljoin
import pandas as pd  # 新增: 用於計算中位數和資料篩選

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

        # 定義要查詢的指標 (來自 dashboard panel id=0)
        # 修改說明：使用與 dashboard 一致的 irate[5s] 瞬時峰值查詢
        # 原始查詢使用 [30s] 和 [1m]，現已調整為 [5s] 以符合 dashboard 設定
        # 新增: logs_per_second_30s 用於中位數篩選分析
        queries = [
            {
                "name": "logs_per_second",
                "query": "sum(irate(logs_received_total[5s]))",
                "description": "日誌數 (logs/s) - 瞬時峰值"
            },
            {
                "name": "logs_per_second_30s",
                "query": "sum(rate(logs_received_total[30s]))",
                "description": "日誌數 (logs/s) - 30秒平均",
                "filter_by_median": True  # 標記此欄位需要進行中位數篩選
            },
            {
                "name": "redis_messages_per_second",
                "query": "sum(irate(redis_stream_messages_total{status='success'}[5s]))",
                "description": "Redis 訊息 (msg/s) - 瞬時峰值"
            },
            {
                "name": "pg_inserts_per_second",
                "query": "sum(irate(pg_stat_database_tup_inserted{datname=\"logsdb\"}[5s]))",
                "description": "PG 插入 (rows/s) - 瞬時峰值"
            },
            {
                "name": "http_requests_per_second",
                "query": "sum(irate(http_requests_total[5s]))",
                "description": "HTTP 請求 (req/s) - 瞬時峰值"
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

        # 寫入 CSV
        print(f"💾 寫入 CSV: {output_file}")
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

                # 檢查是否需要進行中位數篩選
                if metric.get('filter_by_median', False):
                    # 使用 pandas 計算中位數並篩選
                    df = pd.Series(data_values)
                    median_value = df.median()
                    filtered_values = df[df >= median_value]

                    print(f"      [原始資料]")
                    print(f"      資料筆數: {len(data_values)}")
                    print(f"      最大值: {max(data_values):.2f}")
                    print(f"      最小值: {min(data_values):.2f}")
                    print(f"      平均值: {sum(data_values)/len(data_values):.2f}")
                    print(f"      中位數: {median_value:.2f}")
                    print(f"      ")
                    print(f"      [篩選後資料 (>= 中位數)]")
                    print(f"      篩選後筆數: {len(filtered_values)} ({len(filtered_values)/len(data_values)*100:.1f}%)")
                    print(f"      篩選後平均值: {filtered_values.mean():.2f}")
                    print(f"      篩選後最大值: {filtered_values.max():.2f}")
                    print(f"      篩選後最小值: {filtered_values.min():.2f}")
                else:
                    # 原始統計（不進行篩選）
                    print(f"      最大值: {max(data_values):.2f}")
                    print(f"      最小值: {min(data_values):.2f}")
                    print(f"      平均值: {sum(data_values)/len(data_values):.2f}")

        # 新增功能: 基於 logs_per_second 中位數篩選資料並匯出
        # 計算 logs_per_second 的中位數（排除零值、空值、null值）
        logs_data = all_data.get('logs_per_second', {}).get('data', {})
        if logs_data:
            print()
            print("🔍 開始進行中位數篩選...")

            # 方案2: 排除零值、空值和null值後再計算中位數
            # 收集所有非零、非空、非null的值
            non_zero_logs_values = [
                v for v in logs_data.values()
                if v is not None and v != '' and v > 0
            ]

            if not non_zero_logs_values:
                print("   ⚠️  所有 logs_per_second 資料都是零值/空值/null，無法進行篩選")
                print()
                print("⚠️  無法進行中位數篩選: 沒有有效的 logs_per_second 資料")
                return

            # 使用 pandas 計算非零值的中位數
            logs_values_series = pd.Series(non_zero_logs_values)
            median_logs = logs_values_series.median()

            print(f"   原始資料筆數: {len(logs_data)}")
            print(f"   非零資料筆數: {len(non_zero_logs_values)} ({len(non_zero_logs_values)/len(logs_data)*100:.1f}%)")
            print(f"   非零資料中位數: {median_logs:.2f}")
            print(f"   非零資料平均值: {logs_values_series.mean():.2f}")
            print(f"   非零資料最大值: {logs_values_series.max():.2f}")
            print(f"   非零資料最小值: {logs_values_series.min():.2f}")

            # 篩選出 logs_per_second > 中位數的時間戳記（使用 > 而非 >=）
            filtered_timestamps = [
                ts for ts in sorted_timestamps
                if logs_data.get(ts) is not None and logs_data.get(ts) != '' and logs_data.get(ts) > median_logs
            ]

            print(f"   篩選條件: logs_per_second > {median_logs:.2f}")
            print(f"   篩選後筆數: {len(filtered_timestamps)} ({len(filtered_timestamps)/len(sorted_timestamps)*100:.1f}%)")

            # 匯出篩選後的資料
            filtered_output = output_file.replace('.csv', '_filtered.csv')
            print()
            print(f"💾 寫入篩選後的 CSV: {filtered_output}")

            with open(filtered_output, 'w', newline='', encoding='utf-8-sig') as csvfile:
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

            print(f"✅ 篩選後資料匯出完成!")
            print(f"   檔案: {filtered_output}")
            print(f"   資料筆數: {len(filtered_timestamps)}")
            if filtered_timestamps:
                print(f"   時間範圍: {filtered_timestamps[0]} ~ {filtered_timestamps[-1]}")

            # 顯示篩選後的統計摘要
            print()
            print("📊 篩選後統計摘要:")
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
            print("⚠️  無法進行中位數篩選: logs_per_second 資料不存在")


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


if __name__ == "__main__":
    main()
