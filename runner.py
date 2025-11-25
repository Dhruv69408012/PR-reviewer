import subprocess
import sys
import os
import signal
import time

def get_pid_on_port(port):
    """
    Returns the PID of the process using the given port.
    Works on Windows, Linux, and macOS.
    """
    pid = None
    try:
        if sys.platform.startswith("win"):
            cmd = f"netstat -ano | findstr :{port}"
            result = subprocess.check_output(cmd, shell=True).decode()
            for line in result.splitlines():
                parts = line.strip().split()
                if parts[-1].isdigit():
                    pid = int(parts[-1])
                    break
        else:
            cmd = f"lsof -i :{port} -t"
            result = subprocess.check_output(cmd, shell=True).decode().strip()
            if result:
                pid = int(result.splitlines()[0])
    except subprocess.CalledProcessError:
        pid = None
    return pid

def kill_pid(pid):
    """Kill the process with the given PID."""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=True)
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"Killed process {pid}")
    except Exception as e:
        print(f"Error killing process {pid}: {e}")

ports_to_check = [8000, 8001]

for port in ports_to_check:
    pid = get_pid_on_port(port)
    if pid:
        print(f"Port {port} is in use by PID {pid}, killing it...")
        kill_pid(pid)
    else:
        print(f"No process found on port {port}")

processes = []
files_to_run = ["writer.py", "wclient.py"]

for f in files_to_run:
    print(f"Starting {f}...")
    p = subprocess.Popen(["python", f])
    processes.append(p)
    time.sleep(0.5) 
print("All processes started. PIDs:", [p.pid for p in processes])
