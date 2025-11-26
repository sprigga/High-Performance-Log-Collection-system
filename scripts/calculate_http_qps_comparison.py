#!/usr/bin/env python3
"""
計算並比較主系統和對照組的 HTTP QPS 統計數據
輸出平均數、中位數以及差距倍數
"""

import pandas as pd
import numpy as np
import json

def calculate_stats(csv_file):
    """計算指定 CSV 文件的 HTTP QPS 統計數據"""
    # 讀取 CSV 文件
    df = pd.read_csv(csv_file)

    # 提取 HTTP QPS 欄位（處理可能的 BOM 字元）
    http_qps_column = '2_http_qps (2️⃣ HTTP QPS (req/s))'

    # 如果欄位名稱包含 BOM，嘗試移除
    if http_qps_column not in df.columns:
        # 檢查第一個欄位是否包含 BOM
        first_col = df.columns[0]
        if '\ufeff' in first_col:
            df.columns = [col.replace('\ufeff', '') for col in df.columns]

    # 獲取 HTTP QPS 數據
    http_qps_data = df[http_qps_column].dropna()

    # 計算統計值
    mean_val = http_qps_data.mean()
    median_val = http_qps_data.median()

    return {
        'mean': mean_val,
        'median': median_val,
        'count': len(http_qps_data)
    }

def main():
    # 文件路徑
    monitoring_file = '/home/ubuntu/log-collection-system/test_file/monitoring_throughput_http_qps_top20.csv'
    control_file = '/home/ubuntu/log-collection-system/test_file/control_group_http_qps_top20.csv'

    # 計算統計數據
    monitoring_stats = calculate_stats(monitoring_file)
    control_stats = calculate_stats(control_file)

    # 計算差距倍數
    mean_ratio = monitoring_stats['mean'] / control_stats['mean']
    median_ratio = monitoring_stats['median'] / control_stats['median']

    # 輸出結果
    results = {
        'monitoring_system': {
            'name': '主系統 (Redis + Worker)',
            'mean': round(monitoring_stats['mean'], 2),
            'median': round(monitoring_stats['median'], 2),
            'count': monitoring_stats['count']
        },
        'control_group': {
            'name': '對照組',
            'mean': round(control_stats['mean'], 2),
            'median': round(control_stats['median'], 2),
            'count': control_stats['count']
        },
        'comparison': {
            'mean_ratio': round(mean_ratio, 2),
            'median_ratio': round(median_ratio, 2)
        }
    }

    print(json.dumps(results, indent=2, ensure_ascii=False))

    # 同時輸出易讀格式
    print("\n" + "="*60)
    print("HTTP QPS 效能比較報告")
    print("="*60)
    print(f"\n【主系統 (Redis + Worker)】")
    print(f"  平均值: {results['monitoring_system']['mean']:.2f} req/s")
    print(f"  中位數: {results['monitoring_system']['median']:.2f} req/s")
    print(f"  樣本數: {results['monitoring_system']['count']}")

    print(f"\n【對照組】")
    print(f"  平均值: {results['control_group']['mean']:.2f} req/s")
    print(f"  中位數: {results['control_group']['median']:.2f} req/s")
    print(f"  樣本數: {results['control_group']['count']}")

    print(f"\n【效能提升倍數】")
    print(f"  平均值提升: {results['comparison']['mean_ratio']:.2f}x")
    print(f"  中位數提升: {results['comparison']['median_ratio']:.2f}x")
    print("="*60)

if __name__ == '__main__':
    main()
