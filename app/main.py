"""
FastAPI 主應用程式
"""
import os
import json
import time
import asyncio
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
import redis.asyncio as redis

from database import get_async_db, async_engine, test_db_connection
from models import (
    LogEntryRequest, LogEntryResponse, LogQueryResponse,
    BatchLogQueryResponse, HealthCheckResponse, StatsResponse, Log,
    BatchLogEntryRequest, BatchLogEntryResponse  # 新增批量模型
)

# 匯入 Prometheus 指標模組
from metrics import (
    MetricsMiddleware,
    generate_latest,
    CONTENT_TYPE_LATEST,
    logs_received_total,
    redis_stream_messages_total,
    redis_cache_hits_total,
    redis_cache_misses_total,
    redis_operation_duration_seconds,
    redis_stream_size,
    update_system_metrics,
    batch_processing_duration_seconds,
    logs_processing_errors_total
)

# ==========================================
# 應用程式初始化
# ==========================================
app = FastAPI(
    title="高效能日誌收集系統",
    description="基於 FastAPI + Redis + PostgreSQL 的日誌收集系統",
    version="1.0.0"
)

# 加入 Prometheus Metrics 中間件
app.add_middleware(MetricsMiddleware)

# 實例名稱（用於識別不同的 FastAPI 實例）
INSTANCE_NAME = os.getenv('INSTANCE_NAME', 'fastapi-unknown')

# Redis 配置
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))

# Redis 連線池
redis_client: Optional[redis.Redis] = None

# ==========================================
# 應用程式生命週期
# ==========================================
async def update_metrics_task():
    """背景任務：定期更新系統指標"""
    while True:
        try:
            update_system_metrics()
            # 更新 Redis Stream 大小
            if redis_client:
                stream_len = await redis_client.xlen('logs:stream')
                redis_stream_size.set(stream_len)
        except Exception as e:
            print(f"更新指標失敗: {e}")
        await asyncio.sleep(10)  # 每 10 秒更新一次


@app.on_event("startup")
async def startup_event():
    """
    應用程式啟動時執行
    """
    global redis_client

    print(f"🚀 啟動 FastAPI 實例: {INSTANCE_NAME}")

    # 建立 Redis 連線（使用連線池）
    pool = redis.ConnectionPool(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
        # max_connections=50  # 原始連線池大小
        max_connections=200   # 提升連線池以支援更高並發
    )
    redis_client = redis.Redis(connection_pool=pool)

    # 測試 Redis 連線
    try:
        await redis_client.ping()
        print("✅ Redis 連線成功")
    except Exception as e:
        print(f"❌ Redis 連線失敗: {e}")

    # 測試資料庫連線
    if await test_db_connection():
        print("✅ PostgreSQL 連線成功")
    else:
        print("❌ PostgreSQL 連線失敗")

    # 確保 Redis Stream 消費者群組存在
    try:
        await redis_client.xgroup_create(
            name='logs:stream',
            groupname='log_workers',
            id='0',
            mkstream=True
        )
        print("✅ Redis Stream 群組建立成功")
    except redis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            print("ℹ️ Redis Stream 群組已存在")
        else:
            print(f"❌ Redis Stream 群組建立失敗: {e}")

    # 啟動背景任務：定期更新系統指標
    asyncio.create_task(update_metrics_task())
    print("✅ 系統指標監控已啟動")

@app.on_event("shutdown")
async def shutdown_event():
    """
    應用程式關閉時執行
    """
    global redis_client

    print(f"🛑 關閉 FastAPI 實例: {INSTANCE_NAME}")

    if redis_client:
        await redis_client.close()
        print("✅ Redis 連線已關閉")

# ==========================================
# API 端點 - 健康檢查
# ==========================================
@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """
    健康檢查端點

    檢查項目：
    - Redis 連線狀態
    - PostgreSQL 連線狀態
    """
    checks = {
        "redis": False,
        "postgres": False
    }

    # 檢查 Redis
    try:
        await redis_client.ping()
        checks["redis"] = True
    except Exception as e:
        print(f"Redis 健康檢查失敗: {e}")

    # 檢查 PostgreSQL
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception as e:
        print(f"PostgreSQL 健康檢查失敗: {e}")

    status = "healthy" if all(checks.values()) else "unhealthy"

    return HealthCheckResponse(
        status=status,
        instance=INSTANCE_NAME,
        checks=checks,
        timestamp=datetime.now()
    )

# ==========================================
# API 端點 - 建立日誌（寫入 Redis Stream）
# ==========================================
@app.post("/api/log", response_model=LogEntryResponse)
async def create_log(log: LogEntryRequest):
    """
    接收日誌並快速寫入 Redis Stream

    流程：
    1. 驗證日誌格式
    2. 寫入 Redis Stream
    3. 立即返回（非同步處理）

    預期回應時間：< 5ms
    """
    # 記錄業務指標
    logs_received_total.labels(
        device_id=log.device_id,
        log_level=log.log_level
    ).inc()

    try:
        # 準備日誌資料
        log_dict = {
            "device_id": log.device_id,
            "log_level": log.log_level,
            "message": log.message,
            "log_data": json.dumps(log.log_data) if log.log_data else "{}",
            "timestamp": datetime.now(ZoneInfo("Asia/Taipei")).isoformat()
        }

        # 追蹤 Redis 操作時間
        start_time = time.time()

        # 寫入 Redis Stream（設定最大長度避免記憶體溢出）
        message_id = await redis_client.xadd(
            name="logs:stream",
            fields=log_dict,
            maxlen=100000,  # 保留最近 10 萬筆
            approximate=True  # 使用近似值提升效能
        )

        # 記錄成功
        redis_stream_messages_total.labels(status='success').inc()

        # 記錄操作時間
        duration = time.time() - start_time
        redis_operation_duration_seconds.labels(operation='xadd').observe(duration)

        return LogEntryResponse(
            status="queued",
            message_id=message_id,
            received_at=datetime.now()
        )

    except Exception as e:
        redis_stream_messages_total.labels(status='failed').inc()
        logs_processing_errors_total.labels(error_type='redis_write').inc()
        print(f"寫入 Redis Stream 失敗: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to queue log: {str(e)}")

# ==========================================
# API 端點 - 批量建立日誌（新增高效能端點）
# ==========================================
@app.post("/api/logs/batch", response_model=BatchLogEntryResponse)
async def create_batch_logs(batch: BatchLogEntryRequest):
    """
    批量接收日誌並快速寫入 Redis Stream（使用 pipeline）

    流程：
    1. 驗證日誌格式
    2. 使用 Redis Pipeline 批量寫入
    3. 立即返回（非同步處理）

    預期效能：可處理 10,000+ logs/秒
    """
    batch_size = len(batch.logs)
    start_time = time.time()

    try:
        message_ids = []
        # 修正: 使用 Asia/Taipei 時區
        # current_time = datetime.now().isoformat()  # 原始寫法沒有指定時區
        current_time = datetime.now(ZoneInfo("Asia/Taipei")).isoformat()

        # 使用 Redis Pipeline 批量操作（大幅減少網路往返）
        pipe = redis_client.pipeline()

        for log in batch.logs:
            # 記錄業務指標
            logs_received_total.labels(
                device_id=log.device_id,
                log_level=log.log_level
            ).inc()

            log_dict = {
                "device_id": log.device_id,
                "log_level": log.log_level,
                "message": log.message,
                "log_data": json.dumps(log.log_data) if log.log_data else "{}",
                "timestamp": current_time
            }
            pipe.xadd(
                name="logs:stream",
                fields=log_dict,
                maxlen=100000,
                approximate=True
            )

        # 執行批量操作
        results = await pipe.execute()
        message_ids = [str(r) for r in results]

        # 記錄成功
        redis_stream_messages_total.labels(status='success').inc()

        # 記錄批量處理時間
        duration = time.time() - start_time
        batch_processing_duration_seconds.labels(batch_size=str(batch_size)).observe(duration)

        return BatchLogEntryResponse(
            status="queued",
            count=batch_size,
            message_ids=message_ids,
            received_at=datetime.now()
        )

    except Exception as e:
        redis_stream_messages_total.labels(status='failed').inc()
        logs_processing_errors_total.labels(error_type='batch_redis_write').inc()
        print(f"批量寫入 Redis Stream 失敗: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to queue batch logs: {str(e)}")

# ==========================================
# API 端點 - 查詢日誌（使用快取）
# ==========================================
@app.get("/api/logs/{device_id}", response_model=BatchLogQueryResponse)
async def get_logs(
    device_id: str,
    limit: int = Query(default=100, ge=1, le=1000, description="查詢筆數"),
    db: AsyncSession = Depends(get_async_db)
):
    """
    查詢指定設備的日誌

    流程：
    1. 先查詢 Redis 快取
    2. Cache Miss 時查詢 PostgreSQL
    3. 將結果寫入快取（TTL 5分鐘）

    參數：
    - device_id: 設備ID
    - limit: 查詢筆數（預設100，最多1000）
    """
    cache_key = f"cache:logs:{device_id}:{limit}"

    # 1. 檢查 Redis 快取
    try:
        start_time = time.time()
        cached_data = await redis_client.get(cache_key)
        duration = time.time() - start_time
        redis_operation_duration_seconds.labels(operation='get').observe(duration)

        if cached_data:
            redis_cache_hits_total.inc()
            logs_data = json.loads(cached_data)
            return BatchLogQueryResponse(
                total=len(logs_data),
                source="cache",
                data=[LogQueryResponse(**log) for log in logs_data]
            )
        else:
            redis_cache_misses_total.inc()
    except Exception as e:
        print(f"Redis 快取讀取失敗: {e}")

    # 2. Cache Miss - 查詢資料庫
    try:
        # 查詢日誌
        query = (
            select(Log)
            .where(Log.device_id == device_id)
            .order_by(Log.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(query)
        logs = result.scalars().all()

        # 轉換為回應格式
        logs_data = [
            {
                "id": log.id,
                "device_id": log.device_id,
                "log_level": log.log_level,
                "message": log.message,
                "log_data": log.log_data,
                "created_at": log.created_at.isoformat()
            }
            for log in logs
        ]

        # 3. 寫入快取（TTL 5分鐘）
        try:
            start_time = time.time()
            await redis_client.setex(
                name=cache_key,
                time=300,  # 5分鐘
                value=json.dumps(logs_data, default=str)
            )
            duration = time.time() - start_time
            redis_operation_duration_seconds.labels(operation='set').observe(duration)
        except Exception as e:
            print(f"Redis 快取寫入失敗: {e}")

        return BatchLogQueryResponse(
            total=len(logs_data),
            source="database",
            data=[LogQueryResponse(**log) for log in logs_data]
        )

    except Exception as e:
        print(f"資料庫查詢失敗: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query logs: {str(e)}")

# ==========================================
# API 端點 - 統計資料
# ==========================================
@app.get("/api/stats", response_model=StatsResponse)
async def get_stats(db: AsyncSession = Depends(get_async_db)):
    """
    取得系統統計資料

    統計項目：
    - 總日誌數
    - 各等級日誌數量
    - 最近活躍的設備
    """
    cache_key = "cache:stats"

    # 檢查快取
    try:
        cached_stats = await redis_client.get(cache_key)
        if cached_stats:
            return StatsResponse(**json.loads(cached_stats))
    except Exception as e:
        print(f"統計快取讀取失敗: {e}")

    try:
        # 總日誌數
        total_query = select(func.count(Log.id))
        total_result = await db.execute(total_query)
        total_logs = total_result.scalar()

        # 按等級統計
        level_query = (
            select(Log.log_level, func.count(Log.id))
            .group_by(Log.log_level)
        )
        level_result = await db.execute(level_query)
        logs_by_level = {row[0]: row[1] for row in level_result}

        # 最近活躍的設備
        # 原始寫法有誤：SELECT DISTINCT 需要 ORDER BY 欄位也在 SELECT 中
        # device_query = (
        #     select(Log.device_id)
        #     .distinct()
        #     .order_by(Log.created_at.desc())
        #     .limit(10)
        # )
        device_query = (
            select(Log.device_id, func.max(Log.created_at).label('last_activity'))
            .group_by(Log.device_id)
            .order_by(func.max(Log.created_at).desc())
            .limit(10)
        )
        device_result = await db.execute(device_query)
        recent_devices = [row[0] for row in device_result]

        stats = {
            "total_logs": total_logs or 0,
            "logs_by_level": logs_by_level,
            "recent_devices": recent_devices
        }

        # 寫入快取（TTL 60秒）
        try:
            await redis_client.setex(
                name=cache_key,
                time=60,
                value=json.dumps(stats)
            )
        except Exception as e:
            print(f"統計快取寫入失敗: {e}")

        return StatsResponse(**stats)

    except Exception as e:
        print(f"統計查詢失敗: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

# ==========================================
# API 端點 - 根路徑
# ==========================================
@app.get("/metrics")
async def metrics():
    """Prometheus metrics 端點"""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.get("/")
async def root():
    """
    API 根路徑
    """
    return {
        "service": "高效能日誌收集系統",
        "version": "1.0.0",
        "instance": INSTANCE_NAME,
        "endpoints": {
            "health": "/health",
            "create_log": "POST /api/log",
            "get_logs": "GET /api/logs/{device_id}",
            "stats": "GET /api/stats",
            "metrics": "/metrics",
            "docs": "/docs"
        }
    }

# ==========================================
# 全域例外處理
# ==========================================
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    全域例外處理器
    """
    print(f"未處理的例外: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": str(exc),
            "instance": INSTANCE_NAME
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1
    )
