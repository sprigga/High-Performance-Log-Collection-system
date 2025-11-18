# metrics.py
"""
Prometheus 指標模組 - 用於監控系統效能
"""
from prometheus_client import (
    Counter, Histogram, Gauge, Summary,
    generate_latest, CONTENT_TYPE_LATEST
)
from fastapi import Response
import time
import psutil
import functools

# ==================== HTTP 請求指標 ====================
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

http_request_size_bytes = Summary(
    'http_request_size_bytes',
    'HTTP request size in bytes',
    ['method', 'endpoint']
)

http_response_size_bytes = Summary(
    'http_response_size_bytes',
    'HTTP response size in bytes',
    ['method', 'endpoint']
)

# ==================== Redis 指標 ====================
redis_stream_messages_total = Counter(
    'redis_stream_messages_total',
    'Total messages written to Redis Stream',
    ['status']  # success, failed
)

redis_stream_size = Gauge(
    'redis_stream_size',
    'Current size of Redis Stream'
)

redis_cache_hits_total = Counter(
    'redis_cache_hits_total',
    'Total Redis cache hits'
)

redis_cache_misses_total = Counter(
    'redis_cache_misses_total',
    'Total Redis cache misses'
)

redis_operation_duration_seconds = Histogram(
    'redis_operation_duration_seconds',
    'Redis operation duration',
    ['operation'],  # xadd, get, set, xreadgroup
    buckets=(0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1)
)

# ==================== 資料庫指標 ====================
db_connections_active = Gauge(
    'db_connections_active',
    'Active database connections',
    ['pool']  # master, replica
)

db_connections_idle = Gauge(
    'db_connections_idle',
    'Idle database connections',
    ['pool']
)

db_query_duration_seconds = Histogram(
    'db_query_duration_seconds',
    'Database query duration',
    ['query_type', 'pool'],  # select, insert, update, delete
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

db_queries_total = Counter(
    'db_queries_total',
    'Total database queries',
    ['query_type', 'status']  # success, error
)

# ==================== 業務指標 ====================
logs_received_total = Counter(
    'logs_received_total',
    'Total logs received',
    ['device_id', 'log_level']
)

logs_processing_errors_total = Counter(
    'logs_processing_errors_total',
    'Total log processing errors',
    ['error_type']
)

batch_processing_duration_seconds = Histogram(
    'batch_processing_duration_seconds',
    'Batch processing duration',
    ['batch_size'],
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0)
)

active_devices_total = Gauge(
    'active_devices_total',
    'Total number of active devices'
)

# ==================== 系統資源指標 ====================
system_cpu_usage_percent = Gauge(
    'system_cpu_usage_percent',
    'System CPU usage percentage'
)

system_memory_usage_bytes = Gauge(
    'system_memory_usage_bytes',
    'System memory usage in bytes',
    ['type']  # used, available, total
)

system_disk_usage_bytes = Gauge(
    'system_disk_usage_bytes',
    'System disk usage in bytes',
    ['type']  # used, free, total
)

# ==================== Worker 指標 ====================
worker_active_tasks = Gauge(
    'worker_active_tasks',
    'Number of active worker tasks',
    ['worker_id']
)

worker_processed_logs_total = Counter(
    'worker_processed_logs_total',
    'Total logs processed by worker',
    ['worker_id', 'status']  # success, failed
)

worker_batch_size = Histogram(
    'worker_batch_size',
    'Worker batch size distribution',
    buckets=(10, 25, 50, 100, 200, 500, 1000)
)


# ==================== 裝飾器和輔助函數 ====================
def track_time(metric: Histogram, labels: dict = None):
    """追蹤函數執行時間的裝飾器"""
    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)

        # 根據函數類型返回對應的包裝器
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def update_system_metrics():
    """更新系統資源指標"""
    # CPU 使用率
    cpu_percent = psutil.cpu_percent(interval=None)
    system_cpu_usage_percent.set(cpu_percent)

    # 記憶體使用
    memory = psutil.virtual_memory()
    system_memory_usage_bytes.labels(type='used').set(memory.used)
    system_memory_usage_bytes.labels(type='available').set(memory.available)
    system_memory_usage_bytes.labels(type='total').set(memory.total)

    # 磁碟使用
    disk = psutil.disk_usage('/')
    system_disk_usage_bytes.labels(type='used').set(disk.used)
    system_disk_usage_bytes.labels(type='free').set(disk.free)
    system_disk_usage_bytes.labels(type='total').set(disk.total)


class MetricsMiddleware:
    """FastAPI 中間件用於自動記錄 HTTP 指標"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()

        # 記錄請求大小
        request_size = 0

        async def receive_with_size():
            nonlocal request_size
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                request_size += len(body)
            return message

        # 記錄回應大小
        response_size = 0
        status_code = 500

        async def send_with_size(message):
            nonlocal response_size, status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                response_size += len(body)
            await send(message)

        try:
            await self.app(scope, receive_with_size, send_with_size)
        finally:
            # 記錄指標
            duration = time.time() - start_time
            method = scope["method"]
            path = scope["path"]

            # 簡化路徑（避免高基數問題）
            simplified_path = self._simplify_path(path)

            http_requests_total.labels(
                method=method,
                endpoint=simplified_path,
                status=status_code
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                endpoint=simplified_path
            ).observe(duration)

            http_request_size_bytes.labels(
                method=method,
                endpoint=simplified_path
            ).observe(request_size)

            http_response_size_bytes.labels(
                method=method,
                endpoint=simplified_path
            ).observe(response_size)

    def _simplify_path(self, path: str) -> str:
        """簡化路徑，避免高基數問題"""
        # 將動態路徑參數替換為佔位符
        parts = path.split('/')
        simplified_parts = []
        for part in parts:
            if part and not part.startswith('{'):
                # 檢查是否為動態參數（例如設備ID）
                if self._is_dynamic_param(part):
                    simplified_parts.append('{param}')
                else:
                    simplified_parts.append(part)
            else:
                simplified_parts.append(part)
        return '/'.join(simplified_parts) if simplified_parts else path

    def _is_dynamic_param(self, part: str) -> bool:
        """檢查是否為動態參數"""
        # 如果包含數字或特定模式，視為動態參數
        if any(char.isdigit() for char in part):
            return True
        # 如果超過一定長度且不是已知端點
        known_endpoints = ['api', 'log', 'logs', 'health', 'stats', 'metrics', 'docs', 'openapi.json']
        if part not in known_endpoints and len(part) > 10:
            return True
        return False
