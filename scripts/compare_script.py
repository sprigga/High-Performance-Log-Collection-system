import pandas as pd
import sys

def calculate_average(file_path, column_name):
    """Calculates the average of a specific column in a CSV file."""
    try:
        df = pd.read_csv(file_path)
        if column_name not in df.columns:
            print(f"Error: Column '{column_name}' not found in {file_path}")
            sys.exit(1)
        return df[column_name].astype(float).mean()
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

def main():
    # File paths and column name
    file1 = 'test_file/monitoring_throughput_metrics.csv'
    file2 = 'test_file/control_group_http_qps_top20.csv'
    column = '2_http_qps (2️⃣ HTTP QPS (req/s))'

    # Calculate averages
    avg1 = calculate_average(file1, column)
    avg2 = calculate_average(file2, column)

    # Calculate the ratio
    if avg2 != 0:
        ratio = avg1 / avg2
    else:
        ratio = float('inf') # Handle division by zero

    # Print the results
    print(f"Average QPS in '{file1}': {avg1:.2f}")
    print(f"Average QPS in '{file2}': {avg2:.2f}")
    print(f"'{file1}' 的平均 QPS 是 '{file2}' 的 {ratio:.2f} 倍。")

if __name__ == "__main__":
    main()
