"""
背景 Worker - 從 Redis Stream 消費日誌並批次寫入 PostgreSQL
"""
import os
import json
import time
import signal
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import redis
from sqlalchemy import text
from database import SyncSessionLocal, sync_engine

# 匯入 Prometheus 指標模組
from metrics import redis_operation_duration_seconds

# ==========================================
# 配置
# ==========================================
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
WORKER_NAME = os.getenv('WORKER_NAME', f'worker-{int(time.time())}')

STREAM_NAME = 'logs:stream'
GROUP_NAME = 'log_workers'
BATCH_SIZE = 100  # 每次批次處理 100 筆
BLOCK_MS = 5000   # 阻塞等待 5 秒

# 全域變數
running = True
redis_client = None

# ==========================================
# 訊號處理
# ==========================================
def signal_handler(sig, frame):
    """
    處理 SIGINT 和 SIGTERM 訊號（優雅關閉）
    """
    global running
    print(f"\n🛑 接收到訊號 {sig}，準備關閉 Worker...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==========================================
# Redis 連線
# ==========================================
def init_redis():
    """
    初始化 Redis 連線
    """
    global redis_client

    try:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            max_connections=10
        )

        # 測試連線
        redis_client.ping()
        print(f"✅ Redis 連線成功 ({REDIS_HOST}:{REDIS_PORT})")

        # 確保消費者群組存在
        try:
            redis_client.xgroup_create(
                name=STREAM_NAME,
                groupname=GROUP_NAME,
                id='0',
                mkstream=True
            )
            print(f"✅ 建立消費者群組: {GROUP_NAME}")
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                print(f"ℹ️ 消費者群組已存在: {GROUP_NAME}")
            else:
                raise

        return True

    except Exception as e:
        print(f"❌ Redis 連線失敗: {e}")
        return False

# ==========================================
# 批次寫入 PostgreSQL
# ==========================================
def batch_insert_logs(logs_data):
    """
    批次插入日誌到 PostgreSQL

    參數：
        logs_data: list of dict，包含日誌資料

    返回：
        bool: 是否成功
    """
    if not logs_data:
        return True

    session = SyncSessionLocal()

    try:
        # 使用原生 SQL 批次插入（效能最佳）
        # 原始寫法有誤：混用 :name 和 %(name)s 參數格式
        # stmt = text("""
        #     INSERT INTO logs (device_id, log_level, message, log_data, created_at)
        #     VALUES (:device_id, :log_level, :message, :log_data::jsonb, :created_at)
        # """)
        stmt = text("""
            INSERT INTO logs (device_id, log_level, message, log_data, created_at)
            VALUES (:device_id, :log_level, :message, CAST(:log_data AS jsonb), :created_at)
        """)

        session.execute(stmt, logs_data)
        session.commit()

        print(f"✅ 成功寫入 {len(logs_data)} 筆日誌到資料庫")
        return True

    except Exception as e:
        session.rollback()
        print(f"❌ 批次寫入失敗: {e}")
        return False

    finally:
        session.close()

# ==========================================
# 處理訊息
# ==========================================
def process_messages(messages):
    """
    處理從 Redis Stream 讀取的訊息

    參數：
        messages: Redis Stream 訊息列表

    返回：
        tuple: (logs_to_insert, message_ids)
    """
    logs_to_insert = []
    message_ids = []

    for stream_name, stream_messages in messages:
        for message_id, message_data in stream_messages:
            try:
                # 解析日誌資料
                log_data_str = message_data.get('log_data', '{}')

                # 確保 log_data 是字串格式
                if isinstance(log_data_str, dict):
                    log_data_str = json.dumps(log_data_str)

                # 使用 Asia/Taipei 時區的當前時間，但如果消息中已有時間戳則優先使用
                timestamp_str = message_data.get('timestamp', datetime.now(ZoneInfo("Asia/Taipei")).isoformat())
                log_entry = {
                    'device_id': message_data['device_id'],
                    'log_level': message_data['log_level'],
                    'message': message_data['message'],
                    'log_data': log_data_str,
                    'created_at': timestamp_str
                }

                logs_to_insert.append(log_entry)
                message_ids.append(message_id)

            except Exception as e:
                print(f"❌ 解析訊息失敗 ({message_id}): {e}")
                # 仍然記錄 message_id，以便 ACK（避免重複處理）
                message_ids.append(message_id)

    return logs_to_insert, message_ids

# ==========================================
# 主要工作循環
# ==========================================
def worker_loop():
    """
    Worker 主要工作循環
    """
    global running

    print(f"🚀 啟動 Worker: {WORKER_NAME}")
    print(f"📊 設定: 批次大小={BATCH_SIZE}, 阻塞時間={BLOCK_MS}ms")
    print("-" * 60)

    error_count = 0
    max_errors = 10

    while running:
        try:
            # 追蹤 XREADGROUP 操作時間
            start_time = time.time()
            # 從 Redis Stream 批次讀取訊息
            messages = redis_client.xreadgroup(
                groupname=GROUP_NAME,
                consumername=WORKER_NAME,
                streams={STREAM_NAME: '>'},
                count=BATCH_SIZE,
                block=BLOCK_MS
            )
            # 記錄操作時間
            duration = time.time() - start_time
            redis_operation_duration_seconds.labels(operation='xreadgroup').observe(duration)

            # 沒有新訊息
            if not messages:
                continue

            # 處理訊息
            logs_to_insert, message_ids = process_messages(messages)

            if not logs_to_insert:
                print("⚠️ 沒有有效的日誌資料")
                continue

            # 批次寫入 PostgreSQL
            success = batch_insert_logs(logs_to_insert)

            if success:
                # ACK 已處理的訊息
                for message_id in message_ids:
                    try:
                        redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)
                    except Exception as e:
                        print(f"❌ ACK 失敗 ({message_id}): {e}")

                print(f"📝 處理完成: {len(logs_to_insert)} 筆日誌")
                error_count = 0  # 重置錯誤計數
            else:
                error_count += 1
                print(f"⚠️ 處理失敗，錯誤次數: {error_count}/{max_errors}")

                if error_count >= max_errors:
                    print(f"❌ 錯誤次數過多，停止 Worker")
                    break

                # 等待後重試
                time.sleep(5)

        except redis.exceptions.ConnectionError as e:
            print(f"❌ Redis 連線錯誤: {e}")
            error_count += 1

            if error_count >= max_errors:
                print(f"❌ 連線錯誤次數過多，停止 Worker")
                break

            print(f"⏳ 5秒後重新連線...")
            time.sleep(5)

            # 嘗試重新連線
            if not init_redis():
                print("❌ Redis 重新連線失敗")
                break

        except Exception as e:
            print(f"❌ Worker 發生未預期錯誤: {e}")
            error_count += 1

            if error_count >= max_errors:
                print(f"❌ 錯誤次數過多，停止 Worker")
                break

            time.sleep(1)

# ==========================================
# 清理資源
# ==========================================
def cleanup():
    """
    清理資源
    """
    global redis_client

    print("\n🧹 清理資源...")

    if redis_client:
        try:
            redis_client.close()
            print("✅ Redis 連線已關閉")
        except Exception as e:
            print(f"⚠️ 關閉 Redis 連線時發生錯誤: {e}")

    if sync_engine:
        try:
            sync_engine.dispose()
            print("✅ 資料庫連線池已關閉")
        except Exception as e:
            print(f"⚠️ 關閉資料庫連線池時發生錯誤: {e}")

# ==========================================
# 主程式入口
# ==========================================
def main():
    """
    主程式入口
    """
    print("=" * 60)
    print("  📦 日誌收集系統 - 背景 Worker")
    print("=" * 60)

    # 初始化 Redis
    if not init_redis():
        print("❌ 無法啟動 Worker，Redis 連線失敗")
        sys.exit(1)

    # 測試資料庫連線
    try:
        with sync_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"✅ PostgreSQL 連線成功")
    except Exception as e:
        print(f"❌ PostgreSQL 連線失敗: {e}")
        sys.exit(1)

    print("-" * 60)

    try:
        # 開始工作循環
        worker_loop()
    except KeyboardInterrupt:
        print("\n⚠️ 接收到鍵盤中斷")
    finally:
        cleanup()
        print("👋 Worker 已停止")

if __name__ == "__main__":
    main()
