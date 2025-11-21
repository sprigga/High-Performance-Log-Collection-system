"""
對照組壓力測試腳本 - 測試簡化版系統
直接寫入 PostgreSQL，無負載平衡、連接池、Redis、Worker
"""
import asyncio
import aiohttp
import time
import random
from datetime import datetime
from typing import List

# ==========================================
# 測試配置
# ==========================================
BASE_URL = "http://localhost:18724"  # 對照組端點
NUM_DEVICES = 100                    # 設備數量
LOGS_PER_DEVICE = 100                # 每台設備發送的日誌數
CONCURRENT_LIMIT = 200               # 並發限制
BATCH_SIZE = 5                       # 批次大小
USE_BATCH_API = True                 # 是否使用批量 API
NUM_ITERATIONS = 20                 # 測試執行的循環次數
ITERATION_INTERVAL = 5               # 每次循環之間的間隔時間（秒）

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
    print(f"  • 吞吐量: {throughput:.2f} logs/秒")
    print(f"  • 平均回應時間: {avg_response_time:.2f} ms")
    print(f"  • 最小回應時間: {min_response_time:.2f} ms")
    print(f"  • 最大回應時間: {max_response_time:.2f} ms")

    print(f"\n📉 百分位數：")
    print(f"  • P50 (中位數): {p50:.2f} ms")
    print(f"  • P95: {p95:.2f} ms")
    print(f"  • P99: {p99:.2f} ms")

    if failed_requests > 0:
        print(f"\n❌ 錯誤分析：")
        error_types = {}
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
# 主程式
# ==========================================
async def main():
    """主程式入口"""
    for i in range(NUM_ITERATIONS):
        await stress_test(
            num_devices=NUM_DEVICES,
            logs_per_device=LOGS_PER_DEVICE,
            concurrent_limit=CONCURRENT_LIMIT,
            iteration=NUM_ITERATIONS,
            current_iteration=i + 1
        )

        if i < NUM_ITERATIONS - 1 and ITERATION_INTERVAL > 0:
            print(f"\n⏸️  等待 {ITERATION_INTERVAL} 秒後開始下一輪測試...")
            await asyncio.sleep(ITERATION_INTERVAL)

    print("\n✅ 測試完成")

if __name__ == "__main__":
    asyncio.run(main())
