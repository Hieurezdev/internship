#!/usr/bin/env python3
import sys
import os
import subprocess
import threading
import signal
import time

def pipe_output(process, prefix, color_code):
    """Pipe output from process stdout/stderr to sys.stdout with prefix and color."""
    reset_color = "\033[0m"
    while True:
        line = process.stdout.readline()
        if not line:
            break
        try:
            line_str = line.decode('utf-8', errors='replace')
        except Exception:
            line_str = str(line)
        sys.stdout.write(f"{color_code}{prefix}{reset_color} {line_str}")
        sys.stdout.flush()

def main():
    print("\033[1;36m=== Khởi chạy môi trường Phát triển WoxionChat + ACE ===\033[0m")
    
    # Check virtual environment python
    venv_python = os.path.join(".venv", "bin", "python")
    if not os.path.exists(venv_python):
        venv_python = "python" # fallback to global python
        
    print(f"Sử dụng Python: {venv_python}")
    
    processes = []
    
    # Define color codes
    cyan = "\033[1;36m"
    green = "\033[1;32m"
    
    # 1. Start FastAPI Service (run.py)
    print("🚀 Đang khởi động FastAPI agenticRAG service tại http://127.0.0.1:5002...")
    fastapi_process = subprocess.Popen(
        [venv_python, "run.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1
    )
    processes.append(fastapi_process)
    
    # Start thread to read FastAPI output
    fastapi_thread = threading.Thread(
        target=pipe_output, 
        args=(fastapi_process, "[FastAPI]", cyan), 
        daemon=True
    )
    fastapi_thread.start()
    
    # Wait a bit for FastAPI to start
    time.sleep(2)
    
    # 2. Start Django Service (manage.py runserver)
    print("🚀 Đang khởi động Django Web Server tại http://127.0.0.1:8000...")
    django_process = subprocess.Popen(
        [venv_python, "manage.py", "runserver", "127.0.0.1:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1
    )
    processes.append(django_process)
    
    # Start thread to read Django output
    django_thread = threading.Thread(
        target=pipe_output, 
        args=(django_process, "[Django ]", green), 
        daemon=True
    )
    django_thread.start()
    
    print("\n\033[1;32m✓ Cả hai dịch vụ đã khởi chạy thành công!\033[0m")
    print("💬 Nhấn \033[1;31mCtrl+C\033[0m để dừng cả hai dịch vụ.\n")
    
    # Graceful shutdown handler
    def signal_handler(sig, frame):
        print("\n🛑 Đang tắt các dịch vụ...")
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        print("✓ Đã dừng mọi dịch vụ. Tạm biệt!")
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Keep main thread alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
