# Internal_project
python app deployment on k8s

#!/usr/bin/env python3
import os
import subprocess
import shutil
import time

def check_disk_usage():
    total, used, free = shutil.disk_usage("/")
    print(f"Disk Usage: {used // (2**30)} GB used / {total // (2**30)} GB total")

def check_memory_usage():
    result = subprocess.run(["free", "-h"], capture_output=True, text=True)
    print("Memory Usage:\n", result.stdout)

def check_running_process(process_name):
    result = subprocess.run(["pgrep", "-fl", process_name], capture_output=True, text=True)
    if result.stdout:
        print(f"Process '{process_name}' is running:\n{result.stdout}")
    else:
        print(f"Process '{process_name}' is NOT running.")

def tail_logs(log_file, lines=10):
    try:
        result = subprocess.run(["tail", f"-n{lines}", log_file], capture_output=True, text=True)
        print(f"Last {lines} lines of {log_file}:\n{result.stdout}")
    except FileNotFoundError:
        print(f"Log file {log_file} not found.")

def main():
    print("=== DevOps Daily Check Script ===")
    check_disk_usage()
    check_memory_usage()
    check_running_process("nginx")   # Example: check if nginx is running
    tail_logs("/var/log/messages", 5)  # Example: tail system log

if __name__ == "__main__":
    while True:
        main()
        print("\nSleeping for 60 seconds...\n")
        time.sleep(60)  # Run checks every minute
