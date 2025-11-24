#!/bin/bash
#
# Prometheus 抓取健康檢查腳本
# 用於驗證 1 秒抓取間隔是否穩定運行
#

echo "========================================================================"
echo "  Prometheus 抓取健康檢查"
echo "========================================================================"
echo ""

# 檢查 Prometheus 容器狀態
echo "1️⃣  容器狀態："
echo "------------------------------------------------------------------------"
docker ps --filter "name=log-prometheus" --format "table {{.Names}}\t{{.Status}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null
echo ""

# 檢查 FastAPI 目標健康狀態
echo "2️⃣  目標健康狀態："
echo "------------------------------------------------------------------------"
curl -s 'http://localhost:9090/api/v1/targets' | python3 -c "
import json, sys
data = json.load(sys.stdin)
fastapi_targets = [t for t in data['data']['activeTargets'] if t['labels']['job'] == 'fastapi']
for target in fastapi_targets:
    instance = target['labels']['instance']
    health = target['health']
    interval = target['scrapeInterval']
    duration = float(target['lastScrapeDuration']) * 1000
    error = target['lastError'] or '無'

    status_icon = '✅' if health == 'up' else '❌'
    print(f'{status_icon} {instance}')
    print(f'   抓取間隔: {interval} | 耗時: {duration:.2f} ms | 錯誤: {error}')
" 2>/dev/null
echo ""

# 檢查最近 1 分鐘的數據完整性
echo "3️⃣  數據採樣完整性（最近 1 分鐘）："
echo "------------------------------------------------------------------------"
START=$(expr $(date +%s) - 60)
END=$(date +%s)
curl -s "http://localhost:9090/api/v1/query_range?query=up%7Bjob%3D%22fastapi%22%7D&start=$START&end=$END&step=1" > /tmp/prom_check.json 2>/dev/null

python3 << 'EOF'
import json

with open('/tmp/prom_check.json') as f:
    data = json.load(f)

if data['status'] == 'success':
    for result in data['data']['result']:
        instance = result['metric']['instance']
        values = result['values']
        count = len(values)
        expected = 60
        loss_rate = (1 - count / expected) * 100 if expected > 0 else 0

        if count >= 58:
            status = '✅'
        elif count >= 50:
            status = '⚠️ '
        else:
            status = '❌'

        print(f'{status} {instance}: {count}/{expected} 個數據點 (遺失率: {loss_rate:.1f}%)')
EOF
echo ""

# 檢查 Prometheus 資源使用
echo "4️⃣  資源使用情況："
echo "------------------------------------------------------------------------"
docker stats log-prometheus --no-stream --format "CPU: {{.CPUPerc}} | 記憶體: {{.MemUsage}} ({{.MemPerc}})" 2>/dev/null
echo ""

# 檢查最近的錯誤日誌
echo "5️⃣  最近錯誤日誌（最近 20 行）："
echo "------------------------------------------------------------------------"
ERROR_COUNT=$(docker logs log-prometheus --tail 100 2>&1 | grep -i "error" | wc -l)
WARN_COUNT=$(docker logs log-prometheus --tail 100 2>&1 | grep -i "warn" | wc -l)

if [ "$ERROR_COUNT" -eq 0 ] && [ "$WARN_COUNT" -eq 0 ]; then
    echo "✅ 無錯誤或警告"
else
    echo "錯誤數: $ERROR_COUNT | 警告數: $WARN_COUNT"
    docker logs log-prometheus --tail 100 2>&1 | grep -iE "(error|warn)" | tail -10
fi

echo ""
echo "========================================================================"
echo "  檢查完成"
echo "========================================================================"
