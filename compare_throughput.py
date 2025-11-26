import pandas as pd
import numpy as np

# 讀取兩個 CSV 文件
experimental = pd.read_csv('test_file/throughput_metrics_20251125_214941_filtered.csv')
control = pd.read_csv('test_file/control_group_throughput_metrics_filtered.csv')

print("=" * 80)
print("實驗組數據分析 (throughput_metrics_20251125_214941_filtered.csv)")
print("=" * 80)

# 實驗組有兩種日誌速率：瞬時峰值和30秒平均
exp_instant = experimental['logs_per_second (日誌數 (logs/s) - 瞬時峰值)'].dropna()
exp_30s = experimental['logs_per_second_30s (日誌數 (logs/s) - 30秒平均)'].dropna()

print(f"\n瞬時峰值 (logs/s):")
print(f"  平均值: {exp_instant.mean():.2f}")
print(f"  最大值: {exp_instant.max():.2f}")
print(f"  最小值: {exp_instant.min():.2f}")
print(f"  標準差: {exp_instant.std():.2f}")
print(f"  數據點數: {len(exp_instant)}")

print(f"\n30秒平均值 (logs/s):")
print(f"  平均值: {exp_30s.mean():.2f}")
print(f"  最大值: {exp_30s.max():.2f}")
print(f"  最小值: {exp_30s.min():.2f}")
print(f"  標準差: {exp_30s.std():.2f}")
print(f"  數據點數: {len(exp_30s)}")

print("\n" + "=" * 80)
print("控制組數據分析 (control_group_throughput_metrics_filtered.csv)")
print("=" * 80)

# 控制組只有30秒平均值
ctrl_30s = control['logs_per_second (日誌數 (logs/s) - 30s 平均)'].dropna()

print(f"\n30秒平均值 (logs/s):")
print(f"  平均值: {ctrl_30s.mean():.2f}")
print(f"  最大值: {ctrl_30s.max():.2f}")
print(f"  最小值: {ctrl_30s.min():.2f}")
print(f"  標準差: {ctrl_30s.std():.2f}")
print(f"  數據點數: {len(ctrl_30s)}")

print("\n" + "=" * 80)
print("比較分析（基於 30秒平均值）")
print("=" * 80)

# 比較 30 秒平均值
diff_mean = exp_30s.mean() - ctrl_30s.mean()
ratio = exp_30s.mean() / ctrl_30s.mean()

print(f"\n實驗組 vs 控制組:")
print(f"  實驗組平均: {exp_30s.mean():.2f} logs/s")
print(f"  控制組平均: {ctrl_30s.mean():.2f} logs/s")
print(f"  差異: {diff_mean:.2f} logs/s")
print(f"  倍數: {ratio:.2f}x (實驗組是控制組的 {ratio:.2f} 倍)")
print(f"  提升百分比: {(ratio - 1) * 100:.2f}%")

print("\n" + "=" * 80)
print("其他指標比較")
print("=" * 80)

# 比較 HTTP 請求速率
exp_http = experimental['http_requests_per_second (HTTP 請求 (req/s) - 瞬時峰值)'].dropna()
ctrl_http = control['http_requests_per_second (HTTP 請求 (req/s) - 30s 平均)'].dropna()

print(f"\nHTTP 請求速率:")
print(f"  實驗組平均: {exp_http.mean():.2f} req/s")
print(f"  控制組平均: {ctrl_http.mean():.2f} req/s")
print(f"  倍數: {exp_http.mean() / ctrl_http.mean():.2f}x")

# 比較 PG 插入速率
exp_pg = experimental['pg_inserts_per_second (PG 插入 (rows/s) - 瞬時峰值)'].dropna()
ctrl_pg = control['pg_inserts_per_second (PG 插入 (rows/s) - 30s 平均)'].dropna()

if len(exp_pg) > 0:
    print(f"\nPostgreSQL 插入速率:")
    print(f"  實驗組平均: {exp_pg.mean():.2f} rows/s")
    print(f"  控制組平均: {ctrl_pg.mean():.2f} rows/s")
    print(f"  倍數: {exp_pg.mean() / ctrl_pg.mean():.2f}x")

print("\n" + "=" * 80)
