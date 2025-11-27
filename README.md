# High-Performance Log Collection System

A distributed log collection system based on FastAPI, Redis, and PostgreSQL, designed for handling large-scale concurrent requests.

## 📋 System Architecture

```
Test Devices (100 units)
    ↓
Nginx (Load Balancer) [:18723]
    ↓
FastAPI (2 instances) → Redis Stream → Worker → PostgreSQL
    ↓                    ↓
  Immediate Response   Cached Queries
```

### 🏗️ Architecture Diagram (PlantUML)

![Architecture Diagram](uml/architecture_diagram.png)

<details>
<summary>PlantUML Source Code</summary>

```plantuml
@startuml High-Performance Log Collection System Architecture

!define RECTANGLE class

skinparam backgroundColor #FEFEFE
skinparam componentStyle rectangle
skinparam defaultTextAlignment center
skinparam shadowing false

' === External Layer ===
package "External Layer" #LightYellow {
    actor "Test Devices\n(100 units)" as devices
    note right of devices
        Simulates IoT devices
        sending log data
    end note
}

' === Load Balancing Layer ===
package "Load Balancing Layer" #LightBlue {
    component "**Nginx**\n(Load Balancer)\n:18723 → :80" as nginx {
    }
    note right of nginx
        • Least Connection Algorithm
        • Rate Limiting: 10000 req/s
        • Connection Pool: keepalive 128
        • Worker Connections: 4096
    end note
}

' === Application Layer ===
package "Application Layer" #LightGreen {
    component "**FastAPI Instance 1**\n(6 workers)\nlog-fastapi-1:8000" as fastapi1
    component "**FastAPI Instance 2**\n(4 workers)\nlog-fastapi-2:8000" as fastapi2

    note bottom of fastapi1
        • Async Request Handling
        • Redis Connection Pool: 200
        • Immediate Response (< 5ms)
    end note
}

' === Message Queue Layer ===
package "Message Queue Layer" #Orange {
    database "**Redis 7**\n(Stream + Cache)\n:16891 → :6379" as redis {
    }
    note right of redis
        • Stream: logs:stream
        • Consumer Group: log_workers
        • Max Memory: 512MB
        • Policy: allkeys-lru
        • Cache TTL: 5 min (logs), 60s (stats)
    end note
}

' === Worker Layer ===
package "Worker Layer" #LightPink {
    component "**Background Worker**\nlog-worker" as worker
    note right of worker
        • Batch Processing: 100 logs/batch
        • Block Timeout: 5000ms
        • Auto ACK after DB write
        • Error Retry: max 10 times
    end note
}

' === Database Layer ===
package "Database Layer" #LightCoral {
    database "**PostgreSQL 15**\n(Persistent Storage)\n:15467 → :5432" as postgres {
    }
    note right of postgres
        • Max Connections: 200
        • Shared Buffers: 256MB
        • Effective Cache: 768MB
        • Async Commit: OFF (performance)
        • Connection Pool: 10 + 5 overflow
    end note
}

' === Data Flow - Log Writing (Primary Path) ===
devices -[#blue,bold]-> nginx : "1. POST /api/log\nor /api/logs/batch"
nginx -[#blue,bold]-> fastapi1 : "2. Load Balance\n(least_conn)"
nginx -[#blue,bold]-> fastapi2 : "2. Load Balance\n(least_conn)"
fastapi1 -[#green,bold]-> redis : "3. XADD logs:stream\n(Pipeline for batch)"
fastapi2 -[#green,bold]-> redis : "3. XADD logs:stream\n(Pipeline for batch)"
redis -[#red,bold]-> worker : "4. XREADGROUP\n(batch consume)"
worker -[#purple,bold]-> postgres : "5. Batch INSERT\n(100 logs/batch)"
worker -[#orange,dashed]-> redis : "6. XACK\n(confirm processed)"

' === Data Flow - Log Query (Cache Path) ===
devices -[#gray]..> nginx : "GET /api/logs/{device_id}"
nginx -[#gray]..> fastapi1 : "Query Request"
fastapi1 -[#gray,dashed]..> redis : "Check Cache First"
fastapi1 -[#gray,dashed]..> postgres : "Cache Miss → Query DB"
redis -[#gray,dashed]..> fastapi1 : "Cache Hit → Return"
postgres -[#gray,dashed]..> fastapi1 : "Query Result"

' === Response Flow ===
fastapi1 -[#blue,bold]-> nginx : "7. Return {status: queued}"
fastapi2 -[#blue,bold]-> nginx : "7. Return {status: queued}"
nginx -[#blue,bold]-> devices : "8. Immediate Response\n(< 5ms)"

' === Legend ===
legend right
    |= Color |= Description |
    |<#blue> | Log Write Flow (Primary) |
    |<#green> | Redis Stream Write |
    |<#red> | Batch Consume |
    |<#purple> | Database Write |
    |<#orange> | Message Acknowledgment |
    |<#gray> | Query Flow (Secondary) |
endlegend

title High-Performance Log Collection System\nArchitecture Overview

@enduml
```

</details>

### 🔄 Component Interaction Sequence (PlantUML)

![Sequence Diagram](uml/sequence_diagram.png)

<details>
<summary>PlantUML Source Code</summary>

```plantuml
@startuml Log Writing Sequence

title Log Writing Process - Sequence Diagram

skinparam backgroundColor #FEFEFE
skinparam sequenceMessageAlign center

actor "Client\n(Device)" as client
participant "Nginx\n:18723" as nginx
participant "FastAPI\nInstance" as fastapi
database "Redis\nStream" as redis
participant "Worker" as worker
database "PostgreSQL" as postgres

== Single Log Entry ==
client -> nginx: POST /api/log\n{device_id, log_level, message, log_data}
nginx -> fastapi: Forward Request\n(least_conn algorithm)
activate fastapi
fastapi -> redis: XADD logs:stream\n{log_dict, maxlen=100000}
redis --> fastapi: message_id
fastapi --> nginx: {status: "queued", message_id, received_at}
deactivate fastapi
nginx --> client: 200 OK (< 5ms)

== Batch Log Entry ==
client -> nginx: POST /api/logs/batch\n{logs: [...]}
nginx -> fastapi: Forward Batch Request
activate fastapi
fastapi -> redis: Pipeline XADD x N
redis --> fastapi: [message_ids]
fastapi --> nginx: {status: "queued", count: N, message_ids}
deactivate fastapi
nginx --> client: 200 OK

== Background Processing ==
loop Every 5 seconds (BLOCK_MS)
    worker -> redis: XREADGROUP log_workers\ncount=100
    redis --> worker: [messages] (batch)

    alt Messages Available
        worker -> postgres: Batch INSERT\n(100 logs)
        postgres --> worker: Success
        worker -> redis: XACK (confirm processed)
    else No Messages
        worker -> worker: Wait (blocking)
    end
end

== Log Query (with Cache) ==
client -> nginx: GET /api/logs/{device_id}?limit=100
nginx -> fastapi: Forward Query
activate fastapi

alt Cache Hit
    fastapi -> redis: GET cache:logs:{device_id}:{limit}
    redis --> fastapi: cached_data (JSON)
    fastapi --> nginx: {total, source: "cache", data}
else Cache Miss
    fastapi -> redis: GET cache:logs:{device_id}:{limit}
    redis --> fastapi: null
    fastapi -> postgres: SELECT * FROM logs\nWHERE device_id = ? LIMIT ?
    postgres --> fastapi: logs[]
    fastapi -> redis: SETEX cache_key (TTL 300s)
    fastapi --> nginx: {total, source: "database", data}
end
deactivate fastapi
nginx --> client: 200 OK

@enduml
```

</details>

<!--
### 📊 Deployment Architecture (PlantUML) - REMOVED
原有的部署架構圖表已移除，簡化文檔內容
-->

### 🎯 Architecture Design Principles

| Principle | Implementation | Benefit |
|-----------|----------------|---------|
| **Asynchronous Processing** | Redis Stream as message queue | Decouples request handling from database writes |
| **Batch Optimization** | Worker processes 100 logs per batch | Reduces database I/O overhead by 100x |
| **Connection Pooling** | Redis (200), PostgreSQL (10+5) | Eliminates connection creation overhead |
| **Caching Strategy** | Redis cache with TTL (5min logs, 60s stats) | Reduces database query load |
| **Load Balancing** | Nginx least_conn algorithm | Distributes load evenly across instances |
| **Horizontal Scaling** | Multiple FastAPI/Worker instances | Linear throughput scaling |
| **Fault Tolerance** | Health checks, auto-restart, retry mechanisms | High availability |
| **Back-pressure Control** | Rate limiting (10000 req/s), Stream maxlen | Prevents system overload |
| **Observability** | Prometheus + Grafana monitoring | Real-time performance insights |

### Core Features

- ✅ **High Throughput**: Supports ~23,896 logs/second average (peak: 29,467 logs/second)
- ✅ **Low Latency**: API response time P95 ~60.57ms average (best: 33.93ms)
- ✅ **Asynchronous Processing**: Returns immediately after writing to Redis
- ✅ **Batch Optimization**: Batch writing to the database improves performance
- ✅ **Smart Caching**: Redis cache queries reduce database pressure
- ✅ **Fault Tolerance**: Automatic retries, health checks, 0% error rate (100,000 successful requests)
- ✅ **Comprehensive Monitoring**: Prometheus metrics with Grafana dashboards
- ✅ **Automated Alerting**: AlertManager with customizable alert rules

---

## 📁 Project Structure

```
log-collection-system/
├── app/                          # Application core
│   ├── main.py                   # FastAPI main application (539 lines)
│   ├── worker.py                 # Background Worker (327 lines)
│   ├── database.py               # Database connection configuration (137 lines)
│   ├── models.py                 # ORM models and Pydantic Schema (213 lines)
│   ├── metrics.py                # Prometheus metrics collection (351 lines)
│   ├── Dockerfile                # Application container image
│   └── requirements.txt          # Python dependencies
├── nginx/
│   └── nginx.conf                # Nginx load balancing configuration
├── postgres/
│   └── init.sql                  # Database initialization script
├── monitoring/                   # Monitoring stack
│   ├── prometheus/
│   │   ├── prometheus.yml        # Prometheus configuration
│   │   └── alerts/
│   │       └── app_alerts.yml    # Alert rules
│   └── grafana/
│       ├── provisioning/         # Grafana provisioning configs
│       └── dashboards/
│           └── log-collection-dashboard.json  # Main dashboard (863 lines)
├── tests/
│   └── stress_test.py            # Stress test script (462 lines)
├── docker-compose.yml            # Main services configuration
├── docker-compose.monitoring.yml # Monitoring stack configuration
└── README.md                     # This document
```

---

## 🔄 Application Flow

### 1. Log Writing Process
```
Client → Nginx → FastAPI → Redis Stream → Worker → PostgreSQL
                   ↓
              Immediately returns "queued"
```

1. **Client** sends a POST request to `/api/log` or `/api/logs/batch`
2. **Nginx** load balances to FastAPI instances
3. **FastAPI** writes logs to Redis Stream and returns immediately
4. **Worker** consumes logs from Redis Stream in batches and writes to PostgreSQL

### 2. Log Query Process
```
Client → Nginx → FastAPI → Redis Cache (Hit) → Response
                      ↓ (Miss)
                 PostgreSQL → Cache → Response
```

1. Query Redis cache first
2. If Cache Miss, query PostgreSQL
3. Write results to cache (TTL 5 minutes)

### 3. Core Components

| Component | File | Role |
|---|---|---|
| **API Service** | `app/main.py` | Receives requests, writes to Redis Stream, queries data |
| **Background Worker** | `app/worker.py` | Consumes from Redis Stream in batches, writes to PostgreSQL |
| **Database Layer** | `app/database.py` | Synchronous/asynchronous database connection pool management |
| **Data Models** | `app/models.py` | SQLAlchemy ORM and Pydantic Schema |
| **Metrics Collection** | `app/metrics.py` | Prometheus metrics, middleware for request tracking |

---

## 🔧 Main API Endpoints

| Method | Endpoint | Function | File Location |
|---|---|---|---|
| GET | `/` | Service information | `main.py:493-510` |
| GET | `/health` | Health check (Redis + PostgreSQL) | `main.py:145-181` |
| POST | `/api/log` | Single log entry | `main.py:186-242` |
| POST | `/api/logs/batch` | Batch log entries (1-1000 logs) | `main.py:247-312` |
| GET | `/api/logs/{device_id}` | Query device logs (with caching) | `main.py:317-403` |
| GET | `/api/stats` | System statistics (cached 60s) | `main.py:408-479` |
| GET | `/metrics` | Prometheus metrics endpoint | `main.py:484-490` |
| GET | `/docs` | Swagger UI documentation | Auto-generated |
| GET | `/redoc` | ReDoc documentation | Auto-generated |

---

## 🚀 Quick Start

### Prerequisites

- Docker
- Docker Compose
- Python 3.11+ (for test scripts)
- uv (Python package manager, optional)

### Step 1: Start the System

```bash
# Navigate to the project directory
cd log-collection-system

# Start all services
docker-compose up -d

# Check service status
docker-compose ps
```

Expected output:
```
NAME                COMMAND                  STATUS
log-nginx           "nginx -g 'daemon of…"   Up       (0.0.0.0:18723->80/tcp)
log-fastapi-1       "uvicorn main:app --…"   Up
log-fastapi-2       "uvicorn main:app --…"   Up
log-worker          "python worker.py"       Up
log-redis           "redis-server --appen…"  Up       (0.0.0.0:16891->6379/tcp)
log-postgres        "postgres -c max_conn…"  Up       (0.0.0.0:15467->5432/tcp)
```

### Service Port Mapping

| Service | Internal Container Port | External Port |
|---|---|---|
| Nginx | 80 | **18723** |
| Redis | 6379 | 16891 |
| PostgreSQL | 5432 | 15467 |

### Step 2: Verify Services

```bash
# Health check
curl http://localhost:18723/health

# Expected response
{
  "status": "healthy",
  "instance": "fastapi-1",
  "checks": {
    "redis": true,
    "postgres": true
  },
  "timestamp": "2024-11-14T10:30:00.123456"
}
```

### Step 3: Send Test Logs

```bash
# Send a single log
curl -X POST http://localhost:18723/api/log \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "device_001",
    "log_level": "INFO",
    "message": "Test log message",
    "log_data": {"test": true}
  }'

# Expected response
{
  "status": "queued",
  "message_id": "1699960200000-0",
  "received_at": "2024-11-14T10:30:00.123456"
}
```

### Step 4: Query Logs

```bash
# Query logs for a specific device
curl http://localhost:18723/api/logs/device_001?limit=10

# Expected response
{
  "total": 10,
  "source": "database",
  "data": [
    {
      "id": 1,
      "device_id": "device_001",
      "log_level": "INFO",
      "message": "Test log message",
      "log_data": {"test": true},
      "created_at": "2024-11-14T10:30:00"
    }
  ]
}
```

## 🧪 Stress Testing

### Install Python Dependencies

```bash
cd tests

# Using uv (recommended)
uv pip install aiohttp

# Or using pip
pip install aiohttp
```

### Test Script Configuration

Edit `tests/stress_test.py` to adjust the following parameters:

```python
BASE_URL = "http://localhost:18723"  # API endpoint
NUM_DEVICES = 100                    # Number of simulated devices
LOGS_PER_DEVICE = 100                # Number of logs sent per device
CONCURRENT_LIMIT = 200               # Concurrent connections
BATCH_SIZE = 5                       # Batch size for sending
USE_BATCH_API = True                 # Use batch API
```

### Run Stress Test

```bash
cd tests

# Run with uv
# uv run python stress_test.py

# Or run directly
python stress_test.py
```

Example test report (based on latest stress_test_results_20251127_081458.json):
```
======================================================================
  📈 Stress Test Results Summary (50 Iterations)
======================================================================

⏱️  Time Statistics:
  • Total duration: 282.28 seconds (~4.7 minutes)
  • Test period: 2025-11-27 08:14:58 to 08:19:40
  • Iteration interval: 5 seconds

📊 Request Statistics:
  • Total iterations: 50
  • Batch requests per iteration: 2,000
  • Total logs per iteration: 10,000
  • Total requests: 100,000 (all successful)
  • Total logs processed: 500,000
  • Success rate: 100.0% (0 failures)

⚡ Performance Metrics (Averaged across 50 iterations):
  • Average throughput: 23,895.8 logs/second
  • Throughput range: 13,377.93 - 29,467.40 logs/second
  • Average response time: 18.33 ms
  • Response time range: 14.31 - 30.43 ms avg
  • Minimum response time: 1.06 ms (best across all iterations)
  • Maximum response time: 248.77 ms (worst across all iterations)

📉 Percentiles (Averaged across 50 iterations):
  • P50 (Median): 13.54 ms
  • P95: 60.57 ms (range: 33.93 - 107.07 ms)
  • P99: 96.15 ms (range: 58.28 - 228.83 ms)

🎯 Goal Achievement:
  • Iterations meeting throughput target (≥10,000 logs/s): 50/50 (100%)
  • Iterations meeting P95 latency target (≤100 ms): 47/50 (94%)
  • Iterations meeting both targets: 47/50 (94%)
  • Zero failures: ✅ 100% (50/50 iterations)
```

## 📊 Monitoring System

### Start Monitoring Stack

```bash
# Start the main application first
docker-compose up -d

# Start the monitoring stack
docker-compose -f docker-compose.monitoring.yml up -d

# Check all services
docker-compose ps
docker-compose -f docker-compose.monitoring.yml ps
```

### Monitoring Services

| Service | Port | URL | Credentials |
|---|---|---|---|
| **Grafana** | 3000 | http://localhost:3000 | admin / admin123 |
| **Prometheus** | 9090 | http://localhost:9090 | - |
| **AlertManager** | 9093 | http://localhost:9093 | - |
| **Redis Exporter** | 9121 | http://localhost:9121/metrics | - |
| **PostgreSQL Exporter** | 9187 | http://localhost:9187/metrics | - |
| **Node Exporter** | 9100 | http://localhost:9100/metrics | - |
| **cAdvisor** | 18888 | http://localhost:18888 | - |

### Grafana Dashboard

Access the pre-configured dashboard at: http://localhost:3000/d/log-collection-system

**Dashboard Panels (15 total)**:
1. **QPS** - Queries Per Second (Total, Success, Errors)
2. **HTTP Request Latency** - P50, P95, P99 percentiles
3. **Redis Stream Size** - Current message backlog
4. **Redis Cache Hit Rate** - Cache effectiveness
5. **Redis Operation Latency** - By operation type (XADD, GET, SET, XREADGROUP)
6. **System CPU Usage** - Real-time CPU utilization
7. **System Memory Usage** - Memory consumption
8. **Logs Received Per Second** - By log level
9. **Redis Stream Write Status** - Success vs Failed
10. **System Disk Usage** - Disk space monitoring
11. **PostgreSQL Connection Count** - Active, Idle, Total connections
12. **PostgreSQL Query Statistics** - Commits, Rollbacks, Rows fetched
13. **PostgreSQL Cache Hit Rate** - Database cache efficiency
14. **PostgreSQL Database Size** - Storage usage
15. **PostgreSQL Deadlocks & Conflicts** - Database health

**Auto-refresh**: 10 seconds

### Prometheus Metrics

The system exposes comprehensive metrics at `/metrics` endpoint:

#### HTTP Request Metrics
- `http_requests_total` - Total HTTP requests (Counter)
- `http_request_duration_seconds` - Request duration histogram
  - Buckets: 0.001s to 10s (13 buckets)
  - Percentiles: P50, P95, P99
- `http_request_size_bytes` - Request payload size
- `http_response_size_bytes` - Response payload size

#### Redis Metrics
- `redis_stream_messages_total` - Stream write counter (success/failed)
- `redis_stream_size` - Current stream length (Gauge)
- `redis_cache_hits_total` - Cache hit counter
- `redis_cache_misses_total` - Cache miss counter
- `redis_operation_duration_seconds` - Operation latency histogram
  - Operations: xadd, get, set, xreadgroup
  - Buckets: 0.0001s to 0.1s (9 buckets)

#### Business Metrics
- `logs_received_total` - Total logs received by device_id and log_level
- `logs_processing_errors_total` - Processing errors by error_type
- `batch_processing_duration_seconds` - Batch processing time
- `active_devices_total` - Number of active devices

#### System Metrics (via psutil)
- `system_cpu_usage_percent` - CPU utilization
- `system_memory_usage_bytes` - Memory usage (used/available/total)
- `system_disk_usage_bytes` - Disk usage (used/free/total)

#### Worker Metrics
- `worker_active_tasks` - Active worker tasks
- `worker_processed_logs_total` - Processed logs by worker_id and status
- `worker_batch_size` - Histogram of batch sizes

#### PostgreSQL Metrics (via postgres-exporter)
- `postgres_connections_active` - Active connections
- `postgres_connections_idle` - Idle connections
- `postgres_connections_total` - Total connections
- `postgres_query_duration_seconds` - Query execution time
- `postgres_queries_total` - Total queries by type
- `postgres_database_size_bytes` - Database size
- `postgres_errors_total` - Database errors

### Scrape Configuration

Prometheus scrape intervals:
- **Global default**: 15 seconds
- **FastAPI instances**: 5 seconds (high-frequency metrics)
- **Database exporters**: 10 seconds
- **System metrics**: 10 seconds

**Data retention**: 30 days

### Query Examples

View metrics in Prometheus (http://localhost:9090):

```promql
# Average request latency (P95)
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# QPS by endpoint
sum(rate(http_requests_total[1m])) by (endpoint)

# Redis cache hit rate
rate(redis_cache_hits_total[5m]) / (rate(redis_cache_hits_total[5m]) + rate(redis_cache_misses_total[5m]))

# Active PostgreSQL connections
postgres_connections_active

# System memory usage percentage
(system_memory_usage_bytes{type="used"} / system_memory_usage_bytes{type="total"}) * 100
```

---

## 📊 Management and Operations

### View Logs

```bash
# FastAPI logs
docker-compose logs -f fastapi-1

# Worker logs
docker-compose logs -f worker

# Nginx logs
docker-compose logs -f nginx

# All service logs
docker-compose logs -f
```

### View Statistics

```bash
curl http://localhost:18723/api/stats
```

Example response:
```json
{
  "total_logs": 10000,
  "logs_by_level": {
    "DEBUG": 2000,
    "INFO": 5000,
    "WARNING": 2000,
    "ERROR": 900,
    "CRITICAL": 100
  },
  "recent_devices": ["device_001", "device_002", "device_003"]
}
```

### Connect to Database

```bash
# Enter PostgreSQL container
docker exec -it log-postgres psql -U loguser -d logsdb

# Execute queries
SELECT COUNT(*) FROM logs;
SELECT log_level, COUNT(*) FROM logs GROUP BY log_level;
SELECT * FROM logs ORDER BY created_at DESC LIMIT 10;
```

### Connect to Redis

```bash
# Enter Redis container
docker exec -it log-redis redis-cli

# Check Stream
XINFO STREAM logs:stream
XLEN logs:stream

# Check cache
KEYS cache:*
GET cache:logs:device_001:100
```

## 🛠️ Development Guide

### Adjust Configuration

Edit `docker-compose.yml` to adjust system configuration:

```yaml
# Add FastAPI instance
fastapi-3:
  build: ./app
  command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
  # ... other configurations same as fastapi-1

# Add Worker
worker-2:
  build: ./app
  command: python worker.py
  # ... other configurations same as worker
```

Remember to update `nginx/nginx.conf` accordingly:

```nginx
upstream fastapi_backend {
    server fastapi-1:8000;
    server fastapi-2:8000;
    server fastapi-3:8000;  # New
}
```

### Adjust Batch Size

Edit `app/worker.py`:

```python
BATCH_SIZE = 200  # Change to 200 records per batch
BLOCK_MS = 3000   # Change to 3 seconds block
```

### Adjust Connection Pool

Edit `app/database.py`:

```python
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_size=20,      # Increase to 20
    max_overflow=10,   # Increase to 10
    # ...
)
```

## 📈 Performance Optimization Suggestions

### 1. Increase Instance Count

Increase FastAPI and Worker instances based on load:

```bash
docker-compose up -d --scale fastapi-1=3 --scale worker=3
```

### 2. PostgreSQL Optimization

Edit PostgreSQL configuration in `docker-compose.yml`:

```yaml
postgres:
  command:
    - "-c"
    - "shared_buffers=1GB"        # Increase to 1GB
    - "-c"
    - "effective_cache_size=3GB"  # Increase to 3GB
    - "-c"
    - "work_mem=16MB"             # Increase to 16MB
```

### 3. Redis Optimization

```yaml
redis:
  command: >
    redis-server
    --maxmemory 2gb              # Increase memory
    --maxmemory-policy allkeys-lru
    --appendonly yes
```

### 4. Nginx Tuning

Edit `nginx/nginx.conf`:

```nginx
worker_connections 2048;  # Increase to 2048
keepalive 64;             # Increase keepalive connections
```

## 🧹 Cleaning Up the System

```bash
# Stop all services
docker-compose down

# Stop and delete volumes (⚠️ This will delete all data)
docker-compose down -v

# Clean up unused Docker resources
docker system prune -a
```

## 📚 API Documentation

After the system starts, you can access the auto-generated API documentation:

- Swagger UI: http://localhost:18723/docs
- ReDoc: http://localhost:18723/redoc

---

## 🗄️ Database Schema

### Main Table: logs

```sql
CREATE TABLE logs (
    id BIGSERIAL PRIMARY KEY,
    device_id VARCHAR(50) NOT NULL,
    log_level VARCHAR(20) NOT NULL,
    message TEXT,
    log_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    indexed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### Indexes

- `idx_device_created` - Composite index on (device_id, created_at DESC)
  - Optimizes queries filtering by device with time-based sorting
- `idx_log_level` - Index on log_level
  - Speeds up filtering by log severity
- `idx_created_at` - Index on created_at DESC
  - Optimizes time-based queries and analytics
- `idx_log_data_gin` - GIN index on log_data JSONB field
  - Enables efficient querying of JSON properties

### Additional Tables

- `devices` - Device metadata and status tracking
- `log_statistics` - Daily aggregated statistics by device and level

### Views

- `daily_log_summary` - Aggregated daily logs by device and level
  - Pre-computed view for faster analytics queries

### Functions

- `update_indexed_at()` - Trigger function to update indexed_at on UPDATE
- `cleanup_old_logs(days_to_keep INTEGER)` - Maintenance function to delete old logs
  - Usage: `SELECT cleanup_old_logs(30);` to keep only last 30 days

### Sample Queries

```sql
-- Get logs for specific device
SELECT * FROM logs
WHERE device_id = 'device_001'
ORDER BY created_at DESC
LIMIT 100;

-- Count logs by level
SELECT log_level, COUNT(*)
FROM logs
GROUP BY log_level;

-- Query JSON data
SELECT * FROM logs
WHERE log_data @> '{"error": true}';

-- Get daily summary
SELECT * FROM daily_log_summary
WHERE summary_date >= NOW() - INTERVAL '7 days';
```

---

## ⚙️ Configuration Parameters

### Environment Variables

#### PostgreSQL Configuration
```bash
POSTGRES_HOST=localhost       # Database host
POSTGRES_PORT=5432           # Database port
POSTGRES_USER=loguser        # Database user
POSTGRES_PASSWORD=logpass    # Database password
POSTGRES_DB=logsdb          # Database name
```

#### Redis Configuration
```bash
REDIS_HOST=localhost         # Redis host
REDIS_PORT=6379             # Redis port
```

#### Application Configuration
```bash
INSTANCE_NAME=fastapi-1     # FastAPI instance identifier
WORKER_NAME=worker-1        # Worker instance identifier
TZ=Asia/Taipei             # Timezone
```

### FastAPI Worker Count
`docker-compose.yml`:
```yaml
fastapi-1:
  command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 6
fastapi-2:
  command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 6
```
**Total**: 2 instances × 6 workers = 12 worker processes

### Worker Batch Processing
`app/worker.py:23-24`:
```python
BATCH_SIZE = 100  # Number of records processed per batch
BLOCK_MS = 5000   # Block waiting milliseconds (5 seconds)
```

### Redis Configuration

#### Connection Pool (FastAPI)
`app/main.py:58`:
```python
max_connections=200  # Redis connection pool size
```

#### Connection Pool (Worker)
`app/worker.py`:
```python
max_connections=10   # Worker Redis connection pool
```

#### Stream Settings
```python
STREAM_NAME = "logs:stream"
CONSUMER_GROUP = "log_workers"
STREAM_MAXLEN = 100000  # Approximate max stream length
```

#### Cache Settings
```python
CACHE_TTL_LOGS = 300    # 5 minutes for log queries
CACHE_TTL_STATS = 60    # 60 seconds for statistics
```

### PostgreSQL Connection Pool

#### Asynchronous Pool (FastAPI)
`app/database.py:40-45`:
```python
pool_size=10          # Persistent connections
max_overflow=5        # Additional connections (total: 15)
pool_timeout=30       # Connection timeout (seconds)
pool_recycle=3600     # Recycle connections after 1 hour
pool_pre_ping=True    # Verify connection before use
```

#### Synchronous Pool (Worker)
`app/database.py:25-30`:
```python
pool_size=10          # Persistent connections
max_overflow=5        # Additional connections (total: 15)
pool_timeout=30       # Connection timeout (seconds)
pool_recycle=3600     # Recycle connections after 1 hour
pool_pre_ping=True    # Verify connection before use
```

### Nginx Configuration

#### Rate Limiting
`nginx/nginx.conf:37`:
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10000r/s;
limit_req zone=api_limit burst=20000 nodelay;
```

#### Connection Limits
```nginx
worker_connections 4096;      # Max connections per worker
keepalive 128;               # Upstream keepalive connections
limit_conn_zone $binary_remote_addr zone=conn_limit:10m;
limit_conn conn_limit 1000;  # Max 1000 connections per IP
```

#### Timeouts
```nginx
client_body_timeout 12s;      # Client body timeout
proxy_connect_timeout 5s;     # Backend connection timeout
proxy_send_timeout 10s;       # Backend send timeout
proxy_read_timeout 30s;       # Backend read timeout
```

#### Client Limits
```nginx
client_max_body_size 10m;     # Standard endpoints
client_max_body_size 50m;     # Batch endpoint
```

### PostgreSQL Server Configuration
`docker-compose.yml`:
```bash
max_connections=200           # Maximum concurrent connections
shared_buffers=256MB         # Shared memory buffer
effective_cache_size=768MB   # Expected OS cache
work_mem=8MB                # Memory per operation
synchronous_commit=off       # Async commit for performance
```

### Redis Server Configuration
`docker-compose.yml`:
```bash
maxmemory 512mb              # Maximum memory usage
maxmemory-policy allkeys-lru # Eviction policy
appendonly yes               # AOF persistence
```

---

## 🎯 Technology Stack

### Core Technologies
- **Python 3.11** - Programming language
- **FastAPI 0.109.0** - Web framework
- **Uvicorn 0.27.0** - ASGI server
- **SQLAlchemy 2.0.25** - ORM
- **AsyncPG 0.29.0** - Async PostgreSQL driver
- **Redis 5.0.1** - Python Redis client
- **Pydantic 2.5.3** - Data validation

### Monitoring & Metrics
- **Prometheus** - Metrics collection and storage
- **Grafana** - Metrics visualization
- **AlertManager** - Alert routing and management
- **prometheus-client 0.19.0** - Python Prometheus library
- **psutil 5.9.7** - System metrics collection

### Infrastructure
- **Docker & Docker Compose** - Containerization
- **Nginx** - Reverse proxy and load balancer
- **Redis 7** - In-memory cache and stream
- **PostgreSQL 15** - Relational database

### Testing
- **aiohttp 3.9.1** - Async HTTP client for load testing

---

## 🚀 Performance Characteristics

### Measured Performance (Latest Test Results)

**Test Environment Specifications**:
- **CPU**: Apple Silicon (ARM64 architecture)
- **Memory**: 16 GB RAM
- **Storage**: SSD (NVMe)
- **Operating System**: macOS (Darwin 24.6.0)
- **Docker**: Running all services in containerized environment
- **Network**: Local loopback (localhost)

**Test Configuration** (`tests/stress_test.py`):
- Test Period: 50 iterations over 282.28 seconds (~4.7 minutes)
- Devices: 100
- Logs per device: 100
- Total logs per iteration: 10,000
- Concurrent limit: 200
- Batch size: 5 logs per request
- Batch API: Enabled
- Total requests: 100,000 (all successful)
- Total logs processed: 500,000

**Actual Performance Metrics** (from `test_file/stress_test_results_20251127_081458.json`):
- ✅ **Throughput**: Average 23,895.8 logs/second (Range: 13,377.93 - 29,467.40 logs/second)
- ✅ **P95 Response Time**: Average 60.57 ms (Range: 33.93 - 107.07 ms)
- ✅ **P99 Response Time**: Average 96.15 ms (Range: 58.28 - 228.83 ms)
- ✅ **Error Rate**: 0% (100,000/100,000 successful requests)
- ✅ **Average Response Time**: 18.33 ms

**Performance Targets vs Achieved**:
| Metric | Target | Achieved | Status |
|--------|--------|----------|--------|
| Throughput | ≥ 10,000 logs/sec | ~23,895.8 logs/sec avg (100% iterations met target) | ✅ 2.39x better |
| P95 Latency | ≤ 100 ms | ~60.57 ms avg (94% iterations met target) | ✅ Within target |
| P99 Latency | < 500 ms | ~96.15 ms avg | ✅ 5.20x better |
| Error Rate | 0% | 0% | ✅ Perfect |

**Architecture & Optimizations**:
- 2 FastAPI instances × 6 workers = 12 total worker processes
- Nginx load balancing with least_conn algorithm for even distribution
- Redis Stream buffering with 100k message limit for back-pressure control
- Batch database inserts (100 logs per transaction)
- Connection pooling: Redis (200), PostgreSQL (10+5 overflow)
- Async/await for non-blocking I/O operations

**Optimization Timeline**:
1. Phase 1: Increased workers from 2 to 6 per instance
2. Phase 2: Added batch API endpoint with Redis Pipeline
3. Phase 3: Increased Redis connection pool to 200
4. Phase 4: Optimized batch size (100 → 5) for lower P95
5. Phase 5: Increased Nginx rate limits and keepalive
6. Phase 6: Extended stress testing to 50 iterations for comprehensive analysis
7. Phase 7: System optimization and performance tuning
8. Result: Achieved 100% iterations meeting throughput target (2.39x target), 94% meeting P95 latency target, 0% error rate

### Cache Performance
- Cache TTL: 5 minutes for log queries, 60 seconds for statistics
- Cache hit rate: Expected > 50% for repeated queries
- Cache key pattern: `cache:logs:{device_id}:{limit}`

---

## 🎯 Completed Features & Next Steps

### ✅ Completed
1. ✅ **High-Performance API** - FastAPI with async/await
2. ✅ **Load Balancing** - Nginx with least_conn algorithm
3. ✅ **Message Queue** - Redis Streams for async processing
4. ✅ **Batch Processing** - Worker batch inserts (100 logs/batch)
5. ✅ **Smart Caching** - Redis cache with TTL
6. ✅ **Monitoring System** - Prometheus + Grafana with 15 dashboard panels
7. ✅ **Automated Alerting** - 7 pre-configured alert rules
8. ✅ **Comprehensive Metrics** - HTTP, Redis, PostgreSQL, System, Business metrics
9. ✅ **Stress Testing** - Automated load testing with detailed reports
10. ✅ **Database Optimization** - Indexes, connection pooling, batch inserts

### 🔜 Future Enhancements

**Phase 1: Analytics & Intelligence**
1. **Log Analysis**: Integrate ELK Stack (Elasticsearch, Logstash, Kibana)
2. **Anomaly Detection**: ML-based pattern recognition
3. **Advanced Querying**: Full-text search and log aggregation

**Phase 2: High Availability**
1. **Redis Cluster**: Multi-node Redis setup
2. **PostgreSQL Replication**: Primary-standby configuration
3. **Data Backup**: Automated backup and restore procedures

**Phase 3: Scalability**
1. **Kubernetes Deployment**: Container orchestration
2. **Auto-scaling**: Dynamic resource allocation
3. **Multi-region**: Geographic distribution

**Phase 4: Security & Compliance**
1. **Authentication**: JWT-based API authentication
2. **Authorization**: Role-based access control (RBAC)
3. **Encryption**: TLS/SSL for data in transit
4. **Audit Logging**: Compliance tracking

**Phase 5: Developer Experience**
1. **CLI Tool**: Command-line interface for log management
2. **SDK**: Client libraries for multiple languages
3. **Webhooks**: Real-time event notifications
4. **API Versioning**: Backward compatibility support

## 📝 License

MIT License

## 🤝 Contributions

Welcome to submit Issues and Pull Requests!