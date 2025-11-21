#!/usr/bin/env python3
"""
PostgreSQL 連線監控腳本
用於收集和暴露 PostgreSQL 連線池相關的自定義指標
"""
import os
import time
import asyncio
import asyncpg
from prometheus_client import (
    Gauge, Counter, Histogram, generate_latest,
    CONTENT_TYPE_LATEST, CollectorRegistry
)
from aiohttp import web
import logging

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 自定義註冊表（避免與其他 exporter 衝突）
registry = CollectorRegistry()

# ==================== PostgreSQL 連線池監控指標 ====================

# 連線池狀態
pg_pool_size = Gauge(
    'pg_pool_size',
    'Current size of the connection pool',
    registry=registry
)

pg_pool_max_size = Gauge(
    'pg_pool_max_size',
    'Maximum size of the connection pool',
    registry=registry
)

pg_pool_available_connections = Gauge(
    'pg_pool_available_connections',
    'Number of available connections in the pool',
    registry=registry
)

pg_pool_in_use_connections = Gauge(
    'pg_pool_in_use_connections',
    'Number of connections currently in use',
    registry=registry
)

# 連線獲取統計
pg_connection_acquire_duration_seconds = Histogram(
    'pg_connection_acquire_duration_seconds',
    'Time taken to acquire a connection from the pool',
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=registry
)

pg_connection_acquire_total = Counter(
    'pg_connection_acquire_total',
    'Total number of connection acquisitions',
    ['status'],  # success, timeout, error
    registry=registry
)

# 連線洩漏檢測
pg_connection_leaked_total = Counter(
    'pg_connection_leaked_total',
    'Total number of potentially leaked connections',
    registry=registry
)

pg_connection_long_running_total = Gauge(
    'pg_connection_long_running_total',
    'Number of connections running for more than threshold',
    ['threshold_seconds'],
    registry=registry
)

# 資料庫連線統計（補充 postgres-exporter）
pg_connections_active_queries = Gauge(
    'pg_connections_active_queries',
    'Number of connections with active queries',
    ['datname'],
    registry=registry
)

pg_connections_idle_in_transaction = Gauge(
    'pg_connections_idle_in_transaction',
    'Number of idle in transaction connections',
    ['datname'],
    registry=registry
)

pg_connections_waiting = Gauge(
    'pg_connections_waiting',
    'Number of connections waiting for locks',
    ['datname'],
    registry=registry
)

pg_connection_age_seconds = Histogram(
    'pg_connection_age_seconds',
    'Age of database connections',
    ['state'],
    buckets=(1, 5, 10, 30, 60, 300, 600, 1800, 3600, 7200),
    registry=registry
)

# 連線限制相關
pg_max_connections = Gauge(
    'pg_max_connections',
    'Maximum allowed connections configured in PostgreSQL',
    registry=registry
)

pg_connection_usage_ratio = Gauge(
    'pg_connection_usage_ratio',
    'Ratio of current connections to max connections',
    registry=registry
)

# 系統負載與連線的關聯
pg_connections_per_cpu_core = Gauge(
    'pg_connections_per_cpu_core',
    'Average number of connections per CPU core',
    registry=registry
)


class PostgresConnectionMonitor:
    """PostgreSQL 連線監控器"""

    def __init__(self):
        self.db_url = os.getenv(
            'DATABASE_URL',
            'postgresql://loguser:logpass@postgres:5432/logsdb'
        )
        self.pool = None
        self.running = True
        # 連線使用追蹤（用於檢測洩漏）
        self.connection_usage_times = {}
        self.leak_threshold_seconds = 300  # 5分鐘

    async def init_pool(self):
        """初始化連線池"""
        try:
            self.pool = await asyncpg.create_pool(
                self.db_url,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            logger.info("Connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise

    async def close_pool(self):
        """關閉連線池"""
        if self.pool:
            await self.pool.close()
            logger.info("Connection pool closed")

    async def collect_pool_metrics(self):
        """收集連線池指標"""
        if not self.pool:
            return

        try:
            # 連線池基本指標
            pg_pool_size.set(self.pool.get_size())
            pg_pool_max_size.set(self.pool.get_max_size())
            pg_pool_available_connections.set(self.pool.get_idle_size())
            pg_pool_in_use_connections.set(
                self.pool.get_size() - self.pool.get_idle_size()
            )

        except Exception as e:
            logger.error(f"Error collecting pool metrics: {e}")

    async def collect_connection_stats(self):
        """收集資料庫連線統計"""
        if not self.pool:
            return

        try:
            async with self.pool.acquire() as conn:
                # 獲取 max_connections 設定
                max_conn = await conn.fetchval('SHOW max_connections')
                pg_max_connections.set(int(max_conn))

                # 查詢當前連線狀態
                # 修正：PostgreSQL 9.6+ 使用 wait_event_type 替代 waiting 欄位
                query = """
                SELECT
                    datname,
                    state,
                    CASE WHEN wait_event_type IS NOT NULL THEN TRUE ELSE FALSE END as waiting,
                    EXTRACT(EPOCH FROM (NOW() - backend_start)) as connection_age,
                    EXTRACT(EPOCH FROM (NOW() - state_change)) as state_age,
                    COUNT(*) as count
                FROM pg_stat_activity
                WHERE datname IS NOT NULL
                GROUP BY datname, state, wait_event_type, backend_start, state_change
                """

                rows = await conn.fetch(query)

                # 重置計數器
                active_queries = {}
                idle_in_transaction = {}
                waiting_locks = {}
                total_connections = 0

                for row in rows:
                    datname = row['datname']
                    state = row['state']
                    waiting = row['waiting']
                    # 修正：將 count 和 connection_age 轉換為適當的數值類型
                    count = int(row['count'])
                    connection_age = float(row['connection_age']) if row['connection_age'] else None

                    total_connections += count

                    # 統計不同狀態的連線
                    if state == 'active':
                        active_queries[datname] = active_queries.get(datname, 0) + count
                    elif state == 'idle in transaction':
                        idle_in_transaction[datname] = idle_in_transaction.get(datname, 0) + count

                    if waiting:
                        waiting_locks[datname] = waiting_locks.get(datname, 0) + count

                    # 記錄連線年齡
                    if connection_age is not None:
                        pg_connection_age_seconds.labels(state=state).observe(connection_age)

                # 更新指標
                for datname in ['logsdb']:
                    pg_connections_active_queries.labels(datname=datname).set(
                        active_queries.get(datname, 0)
                    )
                    pg_connections_idle_in_transaction.labels(datname=datname).set(
                        idle_in_transaction.get(datname, 0)
                    )
                    pg_connections_waiting.labels(datname=datname).set(
                        waiting_locks.get(datname, 0)
                    )

                # 計算連線使用率
                if max_conn:
                    ratio = total_connections / int(max_conn)
                    pg_connection_usage_ratio.set(ratio)

                # 計算每個 CPU 核心的平均連線數
                cpu_count_query = "SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active'"
                active_count = await conn.fetchval(cpu_count_query)

                # 假設從環境變數或固定值獲取 CPU 核心數
                cpu_cores = int(os.getenv('CPU_CORES', '4'))
                if cpu_cores > 0:
                    pg_connections_per_cpu_core.set(active_count / cpu_cores)

        except Exception as e:
            logger.error(f"Error collecting connection stats: {e}")

    async def detect_connection_leaks(self):
        """檢測連線洩漏"""
        if not self.pool:
            return

        try:
            async with self.pool.acquire() as conn:
                # 查詢長時間運行的連線
                query = """
                SELECT
                    pid,
                    datname,
                    usename,
                    application_name,
                    state,
                    EXTRACT(EPOCH FROM (NOW() - state_change)) as idle_time,
                    EXTRACT(EPOCH FROM (NOW() - query_start)) as query_time
                FROM pg_stat_activity
                WHERE state != 'idle'
                    AND backend_type = 'client backend'
                    AND pid != pg_backend_pid()
                """

                rows = await conn.fetch(query)

                # 統計長時間運行的連線
                long_running_1min = 0
                long_running_5min = 0
                long_running_15min = 0

                for row in rows:
                    # 修正：將 Decimal 類型轉換為 float
                    query_time = float(row['query_time']) if row['query_time'] else 0
                    idle_time = float(row['idle_time']) if row['idle_time'] else 0
                    max_time = max(query_time, idle_time)

                    if max_time > 60:
                        long_running_1min += 1
                    if max_time > 300:
                        long_running_5min += 1
                        # 可能的連線洩漏
                        pg_connection_leaked_total.inc()
                    if max_time > 900:
                        long_running_15min += 1

                pg_connection_long_running_total.labels(threshold_seconds='60').set(long_running_1min)
                pg_connection_long_running_total.labels(threshold_seconds='300').set(long_running_5min)
                pg_connection_long_running_total.labels(threshold_seconds='900').set(long_running_15min)

        except Exception as e:
            logger.error(f"Error detecting connection leaks: {e}")

    async def monitor_loop(self):
        """主監控循環"""
        while self.running:
            try:
                await self.collect_pool_metrics()
                await self.collect_connection_stats()
                await self.detect_connection_leaks()

                # 每 10 秒收集一次
                await asyncio.sleep(10)

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(10)

    async def handle_metrics(self, request):
        """處理 metrics 端點請求"""
        # 修正：aiohttp 不支援 content_type 參數包含 charset
        metrics = generate_latest(registry)
        return web.Response(
            body=metrics,
            headers={'Content-Type': CONTENT_TYPE_LATEST}
        )

    async def handle_health(self, request):
        """健康檢查端點"""
        if self.pool:
            try:
                async with self.pool.acquire() as conn:
                    await conn.fetchval('SELECT 1')
                return web.Response(text='OK', status=200)
            except Exception as e:
                return web.Response(text=f'ERROR: {e}', status=503)
        return web.Response(text='Pool not initialized', status=503)

    async def start_server(self, host='0.0.0.0', port=9188):
        """啟動 HTTP 服務器"""
        app = web.Application()
        app.router.add_get('/metrics', self.handle_metrics)
        app.router.add_get('/health', self.handle_health)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        logger.info(f"Metrics server started on {host}:{port}")
        logger.info(f"Metrics endpoint: http://{host}:{port}/metrics")
        logger.info(f"Health endpoint: http://{host}:{port}/health")

    async def run(self):
        """運行監控器"""
        try:
            await self.init_pool()
            await self.start_server()
            await self.monitor_loop()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            await self.close_pool()


def main():
    """主函數"""
    monitor = PostgresConnectionMonitor()
    asyncio.run(monitor.run())


if __name__ == '__main__':
    main()
