#!/bin/bash
# stop_monitoring.sh - 停止監控服務

echo "🛑 停止監控服務..."

# 切換到專案根目錄
cd "$(dirname "$0")/.."

# 停止所有服務
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down

echo "✅ 監控服務已停止"
