"""
壓力測試腳本 - 模擬 100 台設備併發發送日誌
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
# BASE_URL = "http://localhost:8080"  # 原始端口設定
BASE_URL = "http://localhost:18723"  # Nginx 端點（對應 docker-compose.yml 配置）
NUM_DEVICES = 100                   # 設備數量
LOGS_PER_DEVICE = 100               # 每台設備發送的日誌數
# CONCURRENT_LIMIT = 50               # 原始並發限制
# CONCURRENT_LIMIT = 200              # 第一次調整
# CONCURRENT_LIMIT = 500              # 進一步提升並發限制
# CONCURRENT_LIMIT = 100              # 批量模式使用較少並發（原設定）
CONCURRENT_LIMIT = 200              # 提高並發以配合更小的批次
# BATCH_SIZE = 100                    # 原始批次大小（P95 ~316ms）
BATCH_SIZE = 5                     # 減小批次大小以降低 P95 回應時間
USE_BATCH_API = True               # 是否使用批量 API（新增）
# 新增：循環測試配置
NUM_ITERATIONS = 20                  # 測試執行的循環次數（預設 1 次）
ITERATION_INTERVAL = 5              # 每次循環之間的間隔時間（秒，預設 0 秒）

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
) -> List[dict]:
    """
    批次發送日誌（使用信號量控制並發）
    """
    if USE_BATCH_API:
        # 使用批量 API（高效能模式）
        # 將日誌分成多個小批次發送
        all_logs = [generate_log_data(device_id, log_num) for log_num in range(num_logs)]
        results = []

        # 按 BATCH_SIZE 分割成多個批次
        for i in range(0, len(all_logs), BATCH_SIZE):
            batch = all_logs[i:i + BATCH_SIZE]
            async with semaphore:
                result = await send_batch_logs(session, batch)
                results.append(result)

        return results
    else:
        # 原始單筆發送模式
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
    print("=" * 70)
    # 修改：顯示當前循環資訊
    if iteration > 1:
        print(f"  📊 日誌收集系統 - 壓力測試 [第 {current_iteration}/{iteration} 輪]")
    else:
        print("  📊 日誌收集系統 - 壓力測試")
    print("=" * 70)
    print(f"測試配置：")
    print(f"  • 設備數量: {num_devices}")
    print(f"  • 每台設備日誌數: {logs_per_device}")
    print(f"  • 總日誌數: {num_devices * logs_per_device:,}")
    print(f"  • 並發限制: {concurrent_limit}")
    print(f"  • API 端點: {BASE_URL}")
    # 新增：顯示循環資訊
    if iteration > 1:
        print(f"  • 總循環次數: {iteration}")
        print(f"  • 當前循環: {current_iteration}")
    print("-" * 70)
    
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
        
        print("⏳ 開始發送日誌...")
        
        # 等待所有任務完成
        all_results = await asyncio.gather(*device_tasks)
    
    # 計算總耗時
    total_time = time.time() - start_time
    
    # 整理結果
    all_responses = [result for device_results in all_results for result in device_results]

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
    
    # 錯誤分析
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
    
    # 判斷是否達到目標
    target_throughput = 10000  # 目標：10,000 logs/秒
    target_p95 = 100           # 目標：P95 < 100ms
    
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
# 主程式
# ==========================================
async def main():
    """
    主程式入口
    """
    # 修改：支援多輪循環測試
    for i in range(NUM_ITERATIONS):
        # 執行壓力測試（傳入循環資訊）
        await stress_test(
            num_devices=NUM_DEVICES,
            logs_per_device=LOGS_PER_DEVICE,
            concurrent_limit=CONCURRENT_LIMIT,
            iteration=NUM_ITERATIONS,  # 新增：傳入總循環次數
            current_iteration=i + 1     # 新增：傳入當前循環編號
        )

        # 新增：如果不是最後一輪，等待間隔時間
        if i < NUM_ITERATIONS - 1 and ITERATION_INTERVAL > 0:
            print(f"\n⏸️  等待 {ITERATION_INTERVAL} 秒後開始下一輪測試...")
            await asyncio.sleep(ITERATION_INTERVAL)

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

if __name__ == "__main__":
    asyncio.run(main())
