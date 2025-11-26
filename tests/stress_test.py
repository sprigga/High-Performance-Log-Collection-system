"""
壓力測試腳本 - 模擬 100 台設備併發發送日誌
"""
import asyncio
import aiohttp
import time
import random
import json
from datetime import datetime, timedelta
from typing import List
import sys
import os

# 新增：整合 Prometheus 查詢功能
try:
    from prometheus_api_client import PrometheusConnect
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    print("⚠️  警告: prometheus_api_client 未安裝，Prometheus 指標查詢功能將被停用")

# ==========================================
# 測試配置
# ==========================================
# BASE_URL = "http://localhost:8080"  # 原始端口設定
BASE_URL = "http://localhost:18723"  # Nginx 端點（對應 docker-compose.yml 配置）

# 新增：Prometheus 配置
PROMETHEUS_URL = "http://localhost:9090"  # Prometheus 服務 URL

# ==========================================
# 方案 A: 延長單次測試時間配置（推薦）
# ==========================================
# NUM_DEVICES = 100                   # 原始設備數量 (單次測試 ~0.8 秒，峰值 2,483 req/s)
NUM_DEVICES = 100                   # 增加設備數量讓單次測試約 3 秒（峰值仍維持 ~2,500 req/s）
LOGS_PER_DEVICE = 100               # 每台設備發送的日誌數

CONCURRENT_LIMIT = 200              # 提高並發以配合更小的批次

# BATCH_SIZE = 100                    # 原始批次大小（P95 ~316ms）
BATCH_SIZE = 5                     # 減小批次大小以降低 P95 回應時間
USE_BATCH_API = True               # 是否使用批量 API（新增）

# 新增：循環測試配置
NUM_ITERATIONS = 50               # 測試執行的循環次數（預設 1 次）
# ITERATION_INTERVAL = 1            # 原設定：1 秒間隔（已棄用，導致數據重疊）
ITERATION_INTERVAL = 5              # 優化後：5 秒間隔（避免數據重疊，配合 irate[5s] 監控）

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
# 新增：Prometheus 指標查詢器類別
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
# 生成測試資料
# ==========================================
def generate_log_data(device_id: str, log_num: int) -> dict:
    """
    生成隨機日誌資料
    """
    log_level = random.choice(LOG_LEVELS)
    message_template = random.choice(LOG_MESSAGES)

    # 根據訊息模板填入變數
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
    """
    發送單筆日誌到 API

    返回：
        dict: {
            "success": bool,
            "response_time": float,
            "status": int,
            "error": str or None
        }
    """
    url = f"{BASE_URL}/api/log"
    log_data = generate_log_data(device_id, log_num)

    start_time = time.time()

    try:
        async with session.post(url, json=log_data, timeout=aiohttp.ClientTimeout(total=10)) as response:
            response_time = (time.time() - start_time) * 1000  # 轉換為毫秒

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
# 發送批量日誌（新增高效能端點）
# ==========================================
async def send_batch_logs(session: aiohttp.ClientSession, logs: List[dict]) -> dict:
    """
    批量發送日誌到 API（使用批量端點）

    返回：
        dict: {
            "success": bool,
            "response_time": float,
            "status": int,
            "error": str or None,
            "count": int
        }
    """
    url = f"{BASE_URL}/api/logs/batch"
    batch_data = {"logs": logs}

    start_time = time.time()

    try:
        async with session.post(url, json=batch_data, timeout=aiohttp.ClientTimeout(total=30)) as response:
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
) -> tuple[List[dict], List[dict]]:
    """
    批次發送日誌（使用信號量控制並發）
    Returns:
        tuple: (results, all_logs) - results包含API響應，all_logs包含發送的日誌
    """
    # 生成所有日誌
    all_logs = [generate_log_data(device_id, log_num) for log_num in range(num_logs)]

    if USE_BATCH_API:
        # 使用批量 API（高效能模式）
        # 將日誌分成多個小批次發送
        results = []

        # 按 BATCH_SIZE 分割成多個批次
        for i in range(0, len(all_logs), BATCH_SIZE):
            batch = all_logs[i:i + BATCH_SIZE]
            async with semaphore:
                result = await send_batch_logs(session, batch)
                results.append(result)

        # 修改：返回結果和生成的日誌數據
        return results, all_logs
    else:
        # 原始單筆發送模式
        async def send_with_semaphore(log_num: int) -> dict:
            async with semaphore:
                return await send_log(session, device_id, log_num)

        tasks = [send_with_semaphore(log_num) for log_num in range(num_logs)]
        results = await asyncio.gather(*tasks)

        # 修改：返回結果和生成的日誌數據
        return results, all_logs

# ==========================================
# 主要壓力測試
# ==========================================
async def stress_test(
    num_devices: int = NUM_DEVICES,
    logs_per_device: int = LOGS_PER_DEVICE,
    concurrent_limit: int = CONCURRENT_LIMIT,
    # 新增參數：循環次數（預設 1 次，保持向後相容）
    iteration: int = 1,
    # 新增參數：當前循環的編號（用於顯示）
    current_iteration: int = 1
):
    """
    執行壓力測試

    參數：
        num_devices: 設備數量
        logs_per_device: 每台設備發送的日誌數
        concurrent_limit: 並發限制
        iteration: 總循環次數（新增）
        current_iteration: 當前循環編號（新增）
    """
    # ==========================================
    # 原測試標題輸出（已移除）
    # 原程式碼：詳細的測試配置輸出已被移除，改為簡潔的進度顯示
    # ==========================================

    # 建立信號量控制並發
    semaphore = asyncio.Semaphore(concurrent_limit)

    # 記錄開始時間
    start_time = time.time()

    # 建立 HTTP Session
    connector = aiohttp.TCPConnector(limit=concurrent_limit, limit_per_host=concurrent_limit)
    timeout = aiohttp.ClientTimeout(total=300)  # 總超時 5 分鐘

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # 為每台設備建立任務
        device_tasks = []

        for device_num in range(num_devices):
            # 修改：加入 'opt_' 前綴以區分優化版測試資料
            device_id = f"opt_device_{device_num:03d}"
            task = batch_send_logs(session, device_id, logs_per_device, semaphore)
            device_tasks.append(task)

        # 原輸出：print("⏳ 開始發送日誌...") 已移除

        # 等待所有任務完成
        all_results = await asyncio.gather(*device_tasks)

    # 計算總耗時
    total_time = time.time() - start_time

    # 整理結果 - 現在每個設備任務返回 (results, logs)
    all_responses = []
    all_sent_logs = []  # 修改：收集所有設備發送的日誌數據

    for device_results, device_logs in all_results:
        all_responses.extend(device_results)
        all_sent_logs.extend(device_logs)  # 修改：收集日誌用於後續匯出

    # 統計資料（考慮批量模式）
    total_requests = len(all_responses)
    successful_requests = sum(1 for r in all_responses if r["success"])
    failed_requests = total_requests - successful_requests
    # 計算實際日誌數量（批量模式下一個請求包含多筆日誌）
    total_logs_sent = sum(r.get("count", 1) for r in all_responses)
    successful_logs = sum(r.get("count", 1) for r in all_responses if r["success"])

    response_times = [r["response_time"] for r in all_responses if r["success"]]

    if response_times:
        avg_response_time = sum(response_times) / len(response_times)
        min_response_time = min(response_times)
        max_response_time = max(response_times)

        # 計算百分位數
        sorted_times = sorted(response_times)
        p50 = sorted_times[int(len(sorted_times) * 0.50)]
        p95 = sorted_times[int(len(sorted_times) * 0.95)]
        p99 = sorted_times[int(len(sorted_times) * 0.99)]
    else:
        avg_response_time = 0
        min_response_time = 0
        max_response_time = 0
        p50 = p95 = p99 = 0

    # 吞吐量按實際日誌數計算（而非請求數）
    throughput = successful_logs / total_time if total_time > 0 else 0

    # 計算 QPS（請求數/秒）
    qps = successful_requests / total_time if total_time > 0 else 0

    # ==========================================
    # 原輸出邏輯（已移除）
    # 原程式碼：詳細的控制台輸出已被移除，改為在測試結束後統一匯出 JSON
    # ==========================================

    # 錯誤分析（用於 JSON 匯出）
    error_types = {}
    if failed_requests > 0:
        for r in all_responses:
            if not r["success"]:
                error = r["error"] or f"HTTP {r['status']}"
                error_types[error] = error_types.get(error, 0) + 1

    # 判斷是否達到目標
    target_throughput = 10000  # 目標：10,000 logs/秒
    target_p95 = 100           # 目標：P95 < 100ms

    # 修改：返回完整測試結果供 JSON 匯出使用
    return {
        "iteration": current_iteration,
        "total_iterations": iteration,
        "timestamp": datetime.now().isoformat(),
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
        },
        "sent_logs_data": all_sent_logs  # 修改：包含這輪測試生成的所有日誌用於匯出
    }

# ==========================================
# 查詢測試
# ==========================================
async def query_test(device_id: str = "device_000"):
    """
    測試查詢 API
    """
    print(f"\n📖 查詢測試: {device_id}")
    print("-" * 70)

    url = f"{BASE_URL}/api/logs/{device_id}?limit=10"

    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            response_time = (time.time() - start_time) * 1000

            if response.status == 200:
                data = await response.json()
                print(f"✅ 查詢成功")
                print(f"  • 回應時間: {response_time:.2f} ms")
                print(f"  • 資料來源: {data.get('source', 'unknown')}")
                print(f"  • 日誌數量: {data.get('total', 0)}")
            else:
                print(f"❌ 查詢失敗: HTTP {response.status}")

# ==========================================
# 原匯出測試輪次日誌函數（已移除）
# ==========================================
# 原程式碼：export_logs_for_iteration 函數已被移除
# 改為在 main() 結束時統一匯出所有測試結果為單一 JSON 檔案

# ==========================================
# 匯出吞吐量指標
# ==========================================
def export_metrics(test_start_time: datetime, test_end_time: datetime):
    """
    測試完成後，匯出 Prometheus 吞吐量指標

    Args:
        test_start_time: 測試開始時間
        test_end_time: 測試結束時間
    """
    print("\n" + "=" * 70)
    print("  📊 匯出 Prometheus 吞吐量指標")
    print("=" * 70)

    # 取得 export_throughput_metrics.py 的路徑
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    export_script = os.path.join(
        project_root, "monitoring", "scripts", "export_throughput_metrics.py"
    )

    if not os.path.exists(export_script):
        print(f"⚠️  找不到匯出腳本: {export_script}")
        return

    # 建立 test_file 資料夾（如果不存在）
    test_file_dir = os.path.join(project_root, "test_file")
    os.makedirs(test_file_dir, exist_ok=True)

    # 匯入匯出工具
    sys.path.insert(0, os.path.join(project_root, "monitoring", "scripts"))
    try:
        from export_throughput_metrics import PrometheusExporter

        # 建立 exporter
        exporter = PrometheusExporter()

        # 修改：固定輸出檔名（不含日期時間），存放到 test_file 資料夾
        # 原程式碼（已註釋）：
        # timestamp_str = test_start_time.strftime("%Y%m%d_%H%M%S")
        # output_file = os.path.join(
        #     test_file_dir, f"throughput_metrics_{timestamp_str}.csv"
        # )
        output_file = os.path.join(
            test_file_dir, "monitoring_throughput_metrics.csv"
        )

        print(f"⏱️  測試時間範圍:")
        print(f"   開始: {test_start_time}")
        print(f"   結束: {test_end_time}")
        print(f"   輸出: {output_file}")
        print()

        # 執行匯出
        exporter.export_throughput_metrics(
            test_start_time, test_end_time, output_file
        )

        # 修改：移除 HTTP QPS Top 20 分析（已改為直接在 export_throughput_metrics 中進行篩選並覆蓋原檔案）
        # 原程式碼（已註釋）：
        # if os.path.exists(output_file):
        #     try:
        #         exporter.filter_http_qps_top20(output_file)
        #     except Exception as e:
        #         print(f"\n⚠️  HTTP QPS Top 20 分析失敗: {e}")
        #         print("   主要匯出檔案不受影響")

    except ImportError as e:
        print(f"❌ 無法匯入 export_throughput_metrics: {e}")
    except Exception as e:
        print(f"❌ 匯出指標時發生錯誤: {e}")
    finally:
        # 移除新增的路徑
        if sys.path[0] == os.path.join(project_root, "monitoring", "scripts"):
            sys.path.pop(0)

# ==========================================
# 主程式
# ==========================================
async def main():
    """
    主程式入口
    """
    # 記錄整體測試開始時間（用於匯出指標）
    overall_start_time = datetime.now()

    # 收集所有測試結果
    all_test_results = []

    # 修改：支援多輪循環測試
    for i in range(NUM_ITERATIONS):
        # 執行壓力測試（傳入循環資訊）
        result = await stress_test(
            num_devices=NUM_DEVICES,
            logs_per_device=LOGS_PER_DEVICE,
            concurrent_limit=CONCURRENT_LIMIT,
            iteration=NUM_ITERATIONS,  # 新增：傳入總循環次數
            current_iteration=i + 1     # 新增：傳入當前循環編號
        )

        # 收集結果（保留完整數據供最後匯出，但不包含 sent_logs_data 以節省內存）
        result_copy = {k: v for k, v in result.items() if k != 'sent_logs_data'}
        all_test_results.append(result_copy)

        # 簡單顯示進度
        print(f"✅ 第 {i + 1}/{NUM_ITERATIONS} 輪測試完成")

        # 新增：如果不是最後一輪，等待間隔時間
        if i < NUM_ITERATIONS - 1 and ITERATION_INTERVAL > 0:
            print(f"\n⏸️  等待 {ITERATION_INTERVAL} 秒後開始下一輪測試...")
            await asyncio.sleep(ITERATION_INTERVAL)

    # 計算時間稀釋修正後的指標
    if NUM_ITERATIONS > 1 and ITERATION_INTERVAL > 0:
        print("\n" + "=" * 70)
        print("  🔬 時間稀釋修正分析")
        print("=" * 70)

        # 計算總工作時間和總等待時間
        total_work_time = sum(r["timing"]["total_time"] for r in all_test_results)
        total_wait_time = ITERATION_INTERVAL * (NUM_ITERATIONS - 1)
        total_elapsed_time = total_work_time + total_wait_time

        # 計算總成功數
        total_requests = sum(r["requests"]["successful_requests"] for r in all_test_results)
        total_logs = sum(r["logs"]["successful_logs"] for r in all_test_results)

        # 實際測量的平均值（含稀釋）
        measured_avg_qps = total_requests / total_elapsed_time
        measured_avg_throughput = total_logs / total_elapsed_time

        # 修正後的值（純工作時間）
        corrected_qps = total_requests / total_work_time
        corrected_throughput = total_logs / total_work_time

        # 工作時間比例
        work_ratio = total_work_time / total_elapsed_time

        print(f"\n⏱️  時間分析：")
        print(f"  • 總工作時間: {total_work_time:.2f} 秒 ({work_ratio*100:.1f}%)")
        print(f"  • 總等待時間: {total_wait_time:.2f} 秒 ({(1-work_ratio)*100:.1f}%)")
        print(f"  • 總經過時間: {total_elapsed_time:.2f} 秒")

        print(f"\n📊 指標對比：")
        print(f"  • 實測平均 QPS: {measured_avg_qps:.2f} req/s (含稀釋)")
        print(f"  • 修正後 QPS: {corrected_qps:.2f} req/s (純工作時間)")
        print(f"  • 稀釋比例: {work_ratio:.2%}")

        print(f"\n  • 實測平均吞吐量: {measured_avg_throughput:.2f} logs/s (含稀釋)")
        print(f"  • 修正後吞吐量: {corrected_throughput:.2f} logs/s (純工作時間)")

        print(f"\n✅ 驗證換算公式：")
        calculated_throughput = corrected_qps * BATCH_SIZE
        throughput_match = abs(calculated_throughput - corrected_throughput) / corrected_throughput < 0.01
        print(f"  • 修正後吞吐量 = 修正後 QPS × BATCH_SIZE")
        print(f"  • {corrected_throughput:.2f} ≈ {corrected_qps:.2f} × {BATCH_SIZE}")
        print(f"  • {corrected_throughput:.2f} ≈ {calculated_throughput:.2f}")
        if throughput_match:
            print(f"  • ✅ 換算公式驗證通過 (誤差 < 1%)")
        else:
            print(f"  • ⚠️  換算公式有偏差")

        print(f"\n💡 Grafana 觀測提示：")
        print(f"  • 如果使用 rate[30s]，Grafana 會顯示: ~{measured_avg_qps:.0f} req/s (含稀釋)")
        print(f"  • 如果使用 irate[5s]，Grafana 在峰值期間會顯示: ~{corrected_qps:.0f} req/s (真實峰值)")
        print(f"  • 兩者差異來自時間稀釋效應: {work_ratio:.0%} 工作時間比例")
        print(f"  • {ITERATION_INTERVAL}秒間隔設計：讓 irate[5s] 捕捉單次測試峰值，避免數據重疊")
        print(f"  • 總循環週期: {total_work_time/NUM_ITERATIONS + ITERATION_INTERVAL:.1f} 秒 (測試 {total_work_time/NUM_ITERATIONS:.1f}s + 間隔 {ITERATION_INTERVAL}s)")

        print("=" * 70)

    # 等待 Worker 處理完成
    print("\n⏳ 等待 5 秒讓 Worker 處理日誌...")
    await asyncio.sleep(5)

    # 執行查詢測試
    # 修改：使用新的 device_id 前綴
    await query_test("opt_device_000")

    # 查詢統計資料
    print(f"\n📊 查詢系統統計...")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/stats") as response:
            if response.status == 200:
                stats = await response.json()
                print(f"  • 總日誌數: {stats.get('total_logs', 0):,}")
                print(f"  • 按等級統計:")
                for level, count in stats.get('logs_by_level', {}).items():
                    print(f"    - {level}: {count:,}")

    # ==========================================
    # 新增：匯出 Prometheus 吞吐量指標
    # ==========================================
    overall_end_time = datetime.now()

    print("\n" + "=" * 70)
    print("⏳ 等待 10 秒讓 Prometheus 收集完整指標...")
    print("=" * 70)
    await asyncio.sleep(10)

    # 執行指標匯出
    export_metrics(overall_start_time, overall_end_time)

    # ==========================================
    # 新增：查詢 Prometheus 指標
    # ==========================================
    prometheus_metrics = None
    if PROMETHEUS_AVAILABLE:
        print("\n" + "=" * 70)
        print("  📊 查詢 Prometheus 指標")
        print("=" * 70)

        try:
            querier = PrometheusMetricsQuerier()
            if querier.test_connection():
                print("✅ 連接到 Prometheus 成功")
                print("⏳ 查詢測試期間的指標...")

                # 查詢測試期間的指標
                prometheus_metrics = querier.query_test_metrics(
                    start_time=overall_start_time,
                    end_time=overall_end_time,
                    batch_size=BATCH_SIZE
                )

                # 顯示查詢結果摘要
                print("\n📈 Prometheus 指標摘要:")
                print(f"  • QPS (所有端點): 最大 {prometheus_metrics['qps']['max']:.2f} req/s, 平均 {prometheus_metrics['qps']['avg']:.2f} req/s")
                print(f"  • QPS (批量端點): 最大 {prometheus_metrics['qps_batch']['max']:.2f} req/s, 平均 {prometheus_metrics['qps_batch']['avg']:.2f} req/s")
                print(f"  • 吞吐量: 最大 {prometheus_metrics['throughput']['max']:.2f} logs/s, 平均 {prometheus_metrics['throughput']['avg']:.2f} logs/s")
                print(f"  • P95 響應時間: 最大 {prometheus_metrics['p95_response_time']['max']:.2f} ms, 平均 {prometheus_metrics['p95_response_time']['avg']:.2f} ms")
                print(f"  • P99 響應時間: 最大 {prometheus_metrics['p99_response_time']['max']:.2f} ms, 平均 {prometheus_metrics['p99_response_time']['avg']:.2f} ms")
                print(f"  • 錯誤率: 最大 {prometheus_metrics['error_rate']['max']:.4f}, 平均 {prometheus_metrics['error_rate']['avg']:.4f}")
            else:
                print("⚠️  無法連接到 Prometheus，跳過指標查詢")
        except Exception as e:
            print(f"❌ 查詢 Prometheus 指標時發生錯誤: {e}")
    else:
        print("\n⚠️  Prometheus 客戶端不可用，跳過指標查詢")

    # ==========================================
    # 匯出所有測試結果為 JSON（包含 Prometheus 指標）
    # ==========================================
    print("\n" + "=" * 70)
    print("  📄 匯出測試結果")
    print("=" * 70)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    test_file_dir = os.path.join(project_root, "test_file")

    # 建立 test_file 資料夾（如果不存在）
    os.makedirs(test_file_dir, exist_ok=True)

    # 產生輸出檔案名稱（使用固定名稱或時間戳記）
    timestamp_str = overall_start_time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(test_file_dir, f"stress_test_results_{timestamp_str}.json")

    # 準備完整的測試報告
    test_report = {
        "test_summary": {
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

if __name__ == "__main__":
    asyncio.run(main())
