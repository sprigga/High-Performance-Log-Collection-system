#!/usr/bin/env python3
"""
從 Prometheus 查詢與壓力測試相關的指標
"""
import sys
import os
from datetime import datetime, timedelta
from prometheus_api_client import PrometheusConnect
import argparse
import time


class PrometheusMetricsQuerier:
    """
    Prometheus 指標查詢器
    """
    def __init__(self, prometheus_url="http://localhost:9090"):
        """
        初始化 Prometheus 連接

        Args:
            prometheus_url (str): Prometheus 服務的 URL
        """
        self.prometheus = PrometheusConnect(url=prometheus_url, disable_ssl=True)
        self.prometheus_url = prometheus_url

    def test_connection(self):
        """
        測試與 Prometheus 的連接
        """
        try:
            # 嘗試獲取一個基本指標來測試連接
            result = self.prometheus.get_current_metric_value("up")
            print(f"✅ 連接到 Prometheus 成功: {self.prometheus_url}")
            return True
        except Exception as e:
            print(f"❌ 無法連接到 Prometheus: {e}")
            return False

    def query_current_metrics(self, batch_size=5):
        """
        查詢當前指標值

        Args:
            batch_size (int): 批次大小，用於計算吞吐量

        Returns:
            dict: 包含當前指標值的字典
        """
        metrics = {}

        # 獲取可用的指標標籤以進行動態查詢
        try:
            all_requests_result = self.prometheus.get_current_metric_value("http_requests_total")
            if all_requests_result:
                # 嘗試獲取任意一個請求的標籤以確定正確的標籤名稱
                sample_labels = all_requests_result[0].get('metric', {})
                print(f"🔍 檢測到的標籤範例: {list(sample_labels.keys())}")

                # 確定端點標籤名稱
                endpoint_label = 'endpoint' if 'endpoint' in sample_labels else 'handler' if 'handler' in sample_labels else None

                if endpoint_label:
                    # QPS (使用 rate 獲取平均速率，因為 irate 需要時間窗口內的多個點)
                    try:
                        qps_result = self.prometheus.custom_query(query='rate(http_requests_total[1m])')
                        metrics['qps'] = qps_result
                    except Exception as e:
                        print(f"⚠️ 查詢 QPS 時發生錯誤: {e}")
                        metrics['qps'] = []

                    # QPS (特定端點)
                    try:
                        qps_batch_result = self.prometheus.custom_query(query=f'rate(http_requests_total{{{endpoint_label}="/api/logs/batch"}}[1m])')
                        metrics['qps_batch'] = qps_batch_result
                    except Exception as e:
                        print(f"⚠️ 查詢批量端點 QPS 時發生錯誤: {e}")
                        metrics['qps_batch'] = []

                    # 吞吐量 (Logs/s) - 基於批量端點 QPS * 批次大小
                    try:
                        throughput_query = f'rate(http_requests_total{{{endpoint_label}="/api/logs/batch"}}[1m]) * {batch_size}'
                        throughput_result = self.prometheus.custom_query(query=throughput_query)
                        metrics['throughput'] = throughput_result
                    except Exception as e:
                        print(f"⚠️ 查詢吞吐量時發生錯誤: {e}")
                        metrics['throughput'] = []
                else:
                    print("⚠️ 找不到端點標籤名稱")
                    metrics['qps'] = []
                    metrics['qps_batch'] = []
                    metrics['throughput'] = []
            else:
                print("⚠️ 找不到 http_requests_total 指標")
                metrics['qps'] = []
                metrics['qps_batch'] = []
                metrics['throughput'] = []

        except Exception as e:
            print(f"⚠️ 獲取 http_requests_total 指標時發生錯誤: {e}")
            metrics['qps'] = []
            metrics['qps_batch'] = []
            metrics['throughput'] = []

        # P95 響應時間
        try:
            p95_response_time_query = 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))'
            p95_result = self.prometheus.custom_query(query=p95_response_time_query)
            metrics['p95_response_time'] = p95_result
        except Exception as e:
            print(f"⚠️ 查詢 P95 響應時間時發生錯誤: {e}")
            metrics['p95_response_time'] = []

        # P99 響應時間
        try:
            p99_response_time_query = 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))'
            p99_result = self.prometheus.custom_query(query=p99_response_time_query)
            metrics['p99_response_time'] = p99_result
        except Exception as e:
            print(f"⚠️ 查詢 P99 響應時間時發生錯誤: {e}")
            metrics['p99_response_time'] = []

        # 平均響應時間
        try:
            avg_response_time_query = 'avg(rate(http_request_duration_seconds_sum[5m])) / avg(rate(http_request_duration_seconds_count[5m]))'
            avg_result = self.prometheus.custom_query(query=avg_response_time_query)
            metrics['avg_response_time'] = avg_result
        except Exception as e:
            print(f"⚠️ 查詢平均響應時間時發生錯誤: {e}")
            metrics['avg_response_time'] = []

        # 錯誤率
        try:
            error_rate_query = 'rate(http_requests_total{status=~"5..|4.."}[1m])'
            error_rate_result = self.prometheus.custom_query(query=error_rate_query)
            metrics['error_rate'] = error_rate_result
        except Exception as e:
            print(f"⚠️ 查詢錯誤率時發生錯誤: {e}")
            metrics['error_rate'] = []

        return metrics

    def query_range_metrics(self, start_time, end_time, step='1s'):
        """
        查詢時間範圍內的指標值

        Args:
            start_time (datetime): 開始時間
            end_time (datetime): 結束時間
            step (str): 時間步長

        Returns:
            dict: 包含時間範圍內指標值的字典
        """
        metrics = {}

        # 獲取標籤名稱
        try:
            all_requests_result = self.prometheus.get_current_metric_value("http_requests_total")
            endpoint_label = 'endpoint'
            if all_requests_result:
                sample_labels = all_requests_result[0].get('metric', {})
                endpoint_label = 'endpoint' if 'endpoint' in sample_labels else 'handler' if 'handler' in sample_labels else 'endpoint'
        except:
            endpoint_label = 'endpoint'  # 默認值

        # QPS (時間範圍)
        try:
            qps_result = self.prometheus.custom_query_range(
                query='rate(http_requests_total[1m])',
                start_time=start_time,
                end_time=end_time,
                step=step
            )
            metrics['qps_range'] = qps_result
        except Exception as e:
            print(f"⚠️ 查詢 QPS 時間範圍時發生錯誤: {e}")
            metrics['qps_range'] = []

        # 吞吐量 (Logs/s) - 時間範圍
        try:
            throughput_query = f'rate(http_requests_total{{{endpoint_label}="/api/logs/batch"}}[1m]) * {5}'
            throughput_result = self.prometheus.custom_query_range(
                query=throughput_query,
                start_time=start_time,
                end_time=end_time,
                step=step
            )
            metrics['throughput_range'] = throughput_result
        except Exception as e:
            print(f"⚠️ 查詢吞吐量時間範圍時發生錯誤: {e}")
            metrics['throughput_range'] = []

        # 錯誤率 (時間範圍)
        try:
            error_rate_result = self.prometheus.custom_query_range(
                query='rate(http_requests_total{status=~"5..|4.."}[1m])',
                start_time=start_time,
                end_time=end_time,
                step=step
            )
            metrics['error_rate_range'] = error_rate_result
        except Exception as e:
            print(f"⚠️ 查詢錯誤率時間範圍時發生錯誤: {e}")
            metrics['error_rate_range'] = []

        return metrics

    def print_current_metrics(self, batch_size=5):
        """
        列印當前指標值
        """
        print("=" * 70)
        print("📊 從 Prometheus 查詢當前指標")
        print("=" * 70)

        # 測試連接
        if not self.test_connection():
            return

        print("\n⏳ 查詢中...")
        metrics = self.query_current_metrics(batch_size=batch_size)

        # 格式化輸出當前指標
        print(f"\n📈 QPS (所有端點, 瞬時):")
        if metrics['qps']:
            for item in metrics['qps']:
                labels = ', '.join([f"{k}={v}" for k, v in item.get('metric', {}).items()])
                value = item.get('value', [None, None])[1]  # [timestamp, value]
                print(f"  • {labels or 'all'}: {value}")
        else:
            print("  • 無資料")

        print(f"\n📈 QPS (批量端點 /api/logs/batch, 瞬時):")
        if metrics['qps_batch']:
            for item in metrics['qps_batch']:
                labels = ', '.join([f"{k}={v}" for k, v in item.get('metric', {}).items()])
                value = item.get('value', [None, None])[1]
                print(f"  • {labels or 'all'}: {value}")
        else:
            print("  • 無資料")

        print(f"\n📊 吞吐量 (Logs/s, 基於批量端點 QPS * {batch_size}):")
        if metrics['throughput']:
            for item in metrics['throughput']:
                labels = ', '.join([f"{k}={v}" for k, v in item.get('metric', {}).items()])
                value = item.get('value', [None, None])[1]
                print(f"  • {labels or 'all'}: {value}")
        else:
            print("  • 無資料")

        print(f"\n⏱️ P95 響應時間:")
        if metrics['p95_response_time']:
            for item in metrics['p95_response_time']:
                labels = ', '.join([f"{k}={v}" for k, v in item.get('metric', {}).items()])
                value = item.get('value', [None, None])[1]
                print(f"  • {labels or 'all'}: {value} 秒")
        else:
            print("  • 無資料")

        print(f"\n⏱️ P99 響應時間:")
        if metrics['p99_response_time']:
            for item in metrics['p99_response_time']:
                labels = ', '.join([f"{k}={v}" for k, v in item.get('metric', {}).items()])
                value = item.get('value', [None, None])[1]
                print(f"  • {labels or 'all'}: {value} 秒")
        else:
            print("  • 無資料")

        print(f"\n⏱️ 平均響應時間:")
        if metrics['avg_response_time']:
            for item in metrics['avg_response_time']:
                labels = ', '.join([f"{k}={v}" for k, v in item.get('metric', {}).items()])
                value = item.get('value', [None, None])[1]
                print(f"  • {labels or 'all'}: {value} 秒")
        else:
            print("  • 無資料")

        print(f"\n❌ 錯誤率 (瞬時):")
        if metrics['error_rate']:
            for item in metrics['error_rate']:
                labels = ', '.join([f"{k}={v}" for k, v in item.get('metric', {}).items()])
                value = item.get('value', [None, None])[1]
                print(f"  • {labels or 'all'}: {value}")
        else:
            print("  • 無資料")

    def print_range_metrics(self, start_time, end_time, step='1s'):
        """
        列印時間範圍內的指標值
        """
        print("=" * 70)
        print("📊 從 Prometheus 查詢時間範圍指標")
        print("=" * 70)

        print(f"⏱️ 時間範圍: {start_time} 到 {end_time}")
        print(f"📊 取樣間隔: {step}")

        # 測試連接
        if not self.test_connection():
            return

        print("\n⏳ 查詢中...")
        metrics = self.query_range_metrics(start_time, end_time, step)

        # 輸出時間範圍指標摘要
        print(f"\n📈 QPS 範圍內最大值:")
        if metrics['qps_range']:
            max_values = []
            for result in metrics['qps_range']:  # 遍歷所有結果（可能有多個時間序列）
                if 'values' in result:
                    values = [float(value[1]) for value in result['values'] if value[1] != 'NaN' and value[1] is not None]
                    if values:
                        max_values.extend(values)
            max_qps = max(max_values, default=0) if max_values else 0
            print(f"  • 最大 QPS: {max_qps}")
        else:
            print("  • 無資料")

        print(f"\n📊 吞吐量範圍內最大值:")
        if metrics['throughput_range']:
            max_values = []
            for result in metrics['throughput_range']:
                if 'values' in result:
                    values = [float(value[1]) for value in result['values'] if value[1] != 'NaN' and value[1] is not None]
                    if values:
                        max_values.extend(values)
            max_throughput = max(max_values, default=0) if max_values else 0
            print(f"  • 最大吞吐量: {max_throughput} logs/s")
        else:
            print("  • 無資料")

        print(f"\n❌ 錯誤率範圍內最大值:")
        if metrics['error_rate_range']:
            max_values = []
            for result in metrics['error_rate_range']:
                if 'values' in result:
                    values = [float(value[1]) for value in result['values'] if value[1] != 'NaN' and value[1] is not None]
                    if values:
                        max_values.extend(values)
            max_error_rate = max(max_values, default=0) if max_values else 0
            print(f"  • 最大錯誤率: {max_error_rate}")
        else:
            print("  • 無資料")


def main():
    parser = argparse.ArgumentParser(description="從 Prometheus 查詢壓力測試相關指標")
    parser.add_argument("--prometheus-url", type=str, default="http://localhost:9090",
                        help="Prometheus 服務的 URL (預設: http://localhost:9090)")
    parser.add_argument("--current", action="store_true",
                        help="查詢當前指標值")
    parser.add_argument("--range", action="store_true",
                        help="查詢時間範圍內的指標值 (需要 --start-time 和 --end-time)")
    parser.add_argument("--start-time", type=str,
                        help="開始時間 (格式: YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--end-time", type=str,
                        help="結束時間 (格式: YYYY-MM-DD HH:MM:SS)")
    parser.add_argument("--batch-size", type=int, default=5,
                        help="批次大小 (預設: 5)")
    parser.add_argument("--step", type=str, default="1s",
                        help="時間範圍查詢的步長 (預設: 1s)")

    args = parser.parse_args()

    # 創建查詢器實例
    querier = PrometheusMetricsQuerier(prometheus_url=args.prometheus_url)

    # 查詢當前指標
    if args.current:
        querier.print_current_metrics(batch_size=args.batch_size)

    # 查詢時間範圍內的指標
    if args.range:
        if not args.start_time or not args.end_time:
            print("❌ 錯誤: 使用 --range 時必須提供 --start-time 和 --end-time")
            parser.print_help()
            return

        try:
            start_time = datetime.strptime(args.start_time, "%Y-%m-%d %H:%M:%S")
            end_time = datetime.strptime(args.end_time, "%Y-%m-%d %H:%M:%S")
            querier.print_range_metrics(start_time, end_time, step=args.step)
        except ValueError as e:
            print(f"❌ 時間格式錯誤: {e}")
            print("正確格式範例: --start-time '2023-01-01 12:00:00' --end-time '2023-01-01 12:05:00'")
            return


if __name__ == "__main__":
    main()