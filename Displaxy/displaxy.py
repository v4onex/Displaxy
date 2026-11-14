#!/usr/bin/env python3
import subprocess
import sys
import time
import os
import signal

# ==========================================
# UNIFIED SCRCPY MULTI-DEVICE MANAGER
# Universal Version (USB, Local Hotspot, Remote Wi-Fi)
# ==========================================

PIDS = []

def cleanup(sig, frame):
    print("\nStopping all scrcpy instances...")
    for p in PIDS:
        if p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
    try:
        subprocess.run([ADB_BIN, "forward", "--remove-all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, cleanup)

SCRCPY_DIR = r"C:\SCRCPY"
SCRCPY_BIN = os.path.join(SCRCPY_DIR, "scrcpy.exe")
ADB_BIN = os.path.join(SCRCPY_DIR, "adb.exe")

if not os.path.isfile(ADB_BIN):
    ADB_BIN = "adb"

SCRCPY_SERVER = os.path.join(SCRCPY_DIR, "scrcpy-server")
if not os.path.isfile(SCRCPY_SERVER):
    SCRCPY_SERVER = os.path.join(SCRCPY_DIR, "scrcpy-server.jar")

if not os.path.isfile(SCRCPY_BIN):
    print(f"Error: Executable not found at {SCRCPY_BIN}!")
    sys.exit(1)

os.environ.pop("ADB", None)

IP_TARGETS = [
    "111.222.33.44:5555",
    "666.777.88.99:0000"
]

def run_cmd(cmd_str, timeout=None):
    try:
        result = subprocess.run(
            cmd_str,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""

def get_raw_devices():
    output = run_cmd(f'"{ADB_BIN}" devices')
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices

def main():
    print(f"=== Windows Engine Started (Binary: {SCRCPY_BIN}) ===")
    print("=== 1. Connecting to network & local Wi-Fi devices ===")
    
    for ip in IP_TARGETS:
        print(f"Attempting connection to IP: {ip}...")
        try:
            subprocess.run([ADB_BIN, "connect", ip], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            print(f"Skipping {ip} (offline or unreachable).")

    time.sleep(1)

    raw_devices = get_raw_devices()
    for dev in raw_devices:
        if ":" not in dev:
            print(f" -> USB device detected ({dev}). Ensuring TCP port 5555 is open...")
            subprocess.run(f'"{ADB_BIN}" -s {dev} tcpip 5555', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(1)

    raw_devices = get_raw_devices()
    if not raw_devices:
        print("Error: No active ADB devices found (USB or Wi-Fi)!")
        sys.exit(1)

    print("=== 2. Discovering and deduplicating physical devices ===")
    seen_serials = []
    devices = []

    for dev in raw_devices:
        hw_serial = run_cmd(f'"{ADB_BIN}" -s {dev} shell getprop ro.serialno')
        if not hw_serial:
            hw_serial = dev

        if hw_serial in seen_serials:
            print(f" -> Skipping duplicate instance {dev} (HW Serial {hw_serial} already active)")
            if ":" in dev:
                subprocess.run(f'"{ADB_BIN}" disconnect {dev}', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            seen_serials.append(hw_serial)
            devices.append(dev)
            print(f" -> [Accepted Unique Device] {dev} (HW Serial: {hw_serial})")

    print("=== 3. Launching scrcpy streams ===")
    port_base = 28183
    
    subprocess.run([ADB_BIN, "forward", "--remove-all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for index, dev in enumerate(devices):
        current_port = port_base + index
        print(f"[OK] Processing device: {dev} on port {current_port}")

        root_check = run_cmd(f'"{ADB_BIN}" -s {dev} shell "su -c \'id\'"', timeout=2)
        
        if "uid=0" in root_check:
            print(" -> Root detected (GSI / NetHunter). Injecting server via su stream...")
            
            prep_cmd = (
                f'"{ADB_BIN}" -s {dev} shell "su -c \'setenforce 0; '
                f'chmod 777 /data/local/tmp; '
                f'chown shell:shell /data/local/tmp; '
                f'chcon u:object_r:shell_data_file:s0 /data/local/tmp\'"'
            )
            subprocess.run(prep_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.isfile(SCRCPY_SERVER):
                push_cmd = (
                    f'"{ADB_BIN}" -s {dev} shell "su -c \'cat > /data/local/tmp/scrcpy-server.jar && '
                    f'chmod 777 /data/local/tmp/scrcpy-server.jar && '
                    f'chown shell:shell /data/local/tmp/scrcpy-server.jar && '
                    f'chcon u:object_r:shell_data_file:s0 /data/local/tmp/scrcpy-server.jar\'"'
                )
                
                try:
                    with open(SCRCPY_SERVER, "rb") as jar_file:
                        subprocess.run(
                            push_cmd,
                            shell=True,
                            input=jar_file.read(),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                except Exception as e:
                    print(f" -> Warning: Failed to stream scrcpy-server: {e}")

            scrcpy_cmd = [
                SCRCPY_BIN,
                "-s", dev,
                f"--port={current_port}",
                "-m", "800",
                "--no-audio",
                "-w"
            ]
        else:
            print(" -> Non-root detected (Standard Mode).")
            scrcpy_cmd = [
                SCRCPY_BIN,
                "-s", dev,
                f"--port={current_port}",
                "--max-size=720",
                "--video-bit-rate=1M",
                "--video-codec=h264",
                "--no-audio",
                "-w"
            ]

        p = subprocess.Popen(scrcpy_cmd)
        PIDS.append(p)
        time.sleep(3)

    print("All streams launched! Press [Ctrl+C] to stop.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        cleanup(None, None)

if __name__ == "__main__":
    main()
