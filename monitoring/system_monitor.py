#!/usr/bin/env python3
# system_monitor.py
"""
系統資源監控工具 - 用於評估專案的系統效能
"""
import psutil
import time
from datetime import datetime
import json
import argparse


def get_system_info():
    """獲取系統資訊"""
    cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    net_io = psutil.net_io_counters()

    return {
        'timestamp': datetime.now().isoformat(),
        'cpu': {
            'total': psutil.cpu_percent(interval=1),
            'per_core': cpu_percent,
            'count': psutil.cpu_count()
        },
        'memory': {
            'total': memory.total,
            'available': memory.available,
            'used': memory.used,
            'percent': memory.percent
        },
        'disk': {
            'total': disk.total,
            'used': disk.used,
            'free': disk.free,
            'percent': disk.percent
        },
        'network': {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv
        }
    }


def format_bytes(bytes_val):
    """格式化位元組顯示"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def print_system_info():
    """漂亮地列印系統資訊"""
    info = get_system_info()

    print("\n" + "=" * 60)
    print(f"時間: {info['timestamp']}")
    print("=" * 60)

    print(f"\nCPU:")
    print(f"  總使用率: {info['cpu']['total']:.1f}%")
    print(f"  每核心使用率: {', '.join([f'{x:.1f}%' for x in info['cpu']['per_core']])}")

    print(f"\n記憶體:")
    print(f"  總量: {format_bytes(info['memory']['total'])}")
    print(f"  已使用: {format_bytes(info['memory']['used'])} ({info['memory']['percent']:.1f}%)")
    print(f"  可用: {format_bytes(info['memory']['available'])}")

    print(f"\n磁碟:")
    print(f"  總量: {format_bytes(info['disk']['total'])}")
    print(f"  已使用: {format_bytes(info['disk']['used'])} ({info['disk']['percent']:.1f}%)")
    print(f"  可用: {format_bytes(info['disk']['free'])}")

    print(f"\n網路:")
    print(f"  發送: {format_bytes(info['network']['bytes_sent'])}")
    print(f"  接收: {format_bytes(info['network']['bytes_recv'])}")


def get_docker_stats():
    """獲取 Docker 容器統計資訊"""
    try:
        import subprocess
        result = subprocess.run(
            ['docker', 'stats', '--no-stream', '--format',
             '{{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception as e:
        return f"無法獲取 Docker 統計: {e}"


def print_docker_stats():
    """列印 Docker 容器統計資訊"""
    print("\n" + "=" * 60)
    print("Docker 容器狀態")
    print("=" * 60)

    stats = get_docker_stats()
    if stats:
        print("容器\t\tCPU%\t記憶體使用\t記憶體%\t網路 I/O\t區塊 I/O")
        print("-" * 80)
        for line in stats.strip().split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 6:
                    container = parts[0][:12]
                    print(f"{container}\t{parts[1]}\t{parts[2]}\t{parts[3]}\t{parts[4]}\t{parts[5]}")
    else:
        print("無法獲取 Docker 統計資訊")


def monitor_loop(interval=5, output_file=None, include_docker=False):
    """持續監控並可選擇輸出到文件"""
    try:
        while True:
            print_system_info()

            if include_docker:
                print_docker_stats()

            if output_file:
                with open(output_file, 'a') as f:
                    info = get_system_info()
                    f.write(json.dumps(info) + '\n')

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n監控已停止")


def check_system_health():
    """檢查系統健康狀態"""
    info = get_system_info()
    warnings = []
    critical = []

    # CPU 檢查
    if info['cpu']['total'] > 90:
        critical.append(f"CPU 使用率過高: {info['cpu']['total']:.1f}%")
    elif info['cpu']['total'] > 70:
        warnings.append(f"CPU 使用率偏高: {info['cpu']['total']:.1f}%")

    # 記憶體檢查
    if info['memory']['percent'] > 90:
        critical.append(f"記憶體使用率過高: {info['memory']['percent']:.1f}%")
    elif info['memory']['percent'] > 80:
        warnings.append(f"記憶體使用率偏高: {info['memory']['percent']:.1f}%")

    # 磁碟檢查
    if info['disk']['percent'] > 90:
        critical.append(f"磁碟使用率過高: {info['disk']['percent']:.1f}%")
    elif info['disk']['percent'] > 80:
        warnings.append(f"磁碟使用率偏高: {info['disk']['percent']:.1f}%")

    print("\n" + "=" * 60)
    print("系統健康檢查")
    print("=" * 60)

    if critical:
        print("\n[嚴重問題]")
        for issue in critical:
            print(f"  - {issue}")

    if warnings:
        print("\n[警告]")
        for issue in warnings:
            print(f"  - {issue}")

    if not critical and not warnings:
        print("\n系統狀態良好！")

    return len(critical) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='系統資源監控工具')
    parser.add_argument('-i', '--interval', type=int, default=5,
                        help='更新間隔(秒), 預設: 5')
    parser.add_argument('-o', '--output', type=str,
                        help='輸出文件路徑')
    parser.add_argument('-d', '--docker', action='store_true',
                        help='包含 Docker 容器監控')
    parser.add_argument('-c', '--check', action='store_true',
                        help='執行一次健康檢查後退出')
    parser.add_argument('-s', '--single', action='store_true',
                        help='只顯示一次系統資訊後退出')

    args = parser.parse_args()

    if args.check:
        print("執行系統健康檢查...")
        healthy = check_system_health()
        exit(0 if healthy else 1)

    if args.single:
        print_system_info()
        if args.docker:
            print_docker_stats()
        exit(0)

    print("開始系統監控...")
    print("按 Ctrl+C 停止")

    monitor_loop(
        interval=args.interval,
        output_file=args.output,
        include_docker=args.docker
    )
