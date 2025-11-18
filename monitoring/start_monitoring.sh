#!/bin/bash
# start_monitoring.sh - 啟動完整監控架構

echo "🚀 啟動完整監控架構..."

# 檢查 Docker 是否運行
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker 未運行，請先啟動 Docker"
    exit 1
fi

# 切換到專案根目錄
cd "$(dirname "$0")/.."

# 啟動所有服務（包括監控）
echo "📦 啟動應用服務和監控服務..."
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d

# 等待服務啟動
echo "⏳ 等待服務啟動..."
sleep 10

# 檢查服務狀態
echo ""
echo "✅ 監控服務已啟動"
echo ""
echo "📊 訪問以下 URL:"
echo "  - 應用 API: http://localhost:18723"
echo "  - Prometheus: http://localhost:9090"
echo "  - Grafana: http://localhost:3000 (admin/admin123)"
echo "  - AlertManager: http://localhost:9093"
echo "  - cAdvisor: http://localhost:8080"
echo "  - Node Exporter: http://localhost:9100/metrics"
echo "  - Redis Exporter: http://localhost:9121/metrics"
echo "  - PostgreSQL Exporter: http://localhost:9187/metrics"
echo ""
echo "🔍 查看服務狀態:"
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml ps
