import time
import board
import busio
import serial
import statistics
from math import isnan
from itertools import filterfalse
import threading
from collections import deque
import json
import requests
import os
from datetime import datetime

from mlx90641 import *
import adafruit_mlx90632

#
# CONSTANTS
#
print("[SYS] Configuring constants...")
N8N_WEBHOOK_URL = "https://fall25engr100.app.n8n.cloud/webhoot/d41a007e-104f-4ed3-b83a-be8656346d7a"
MAX_HISTORY = 50000 # Local records
MEASUREMENT_INTERVAL = 60.0*5.0 # Seconds
SAVE_INTERVAL = MEASUREMENT_INTERVAL*5.0 # Seconds (local save timer)
PUSH_INTERVAL = SAVE_INTERVAL # Seconds (n8n push)
HISTORY_FILE = "/home/hallmatt/project/history.json"
UNIT_ID = 1

#
# CONFIGURATION
#
"""CAMERA CONFIG"""
print("[CAM] Configuring camera...")
dev = MLX90641()
r = dev.i2c_init("/dev/i2c-1")
r = dev.set_refresh_rate(1) # Hz
refresh_rate = dev.get_refresh_rate()
"""FIR CONFIG"""
print("[FIR] Configuring FIR sensor...")
i2c = board.I2C()
mlx = adafruit_mlx90632.MLX90632(i2c)
mlx.measurement_select = adafruit_mlx90632.EXTENDED_RANGE
mlx.mode = adafruit_mlx90632.MODE_CONTINUOUS
mlx.refresh_rate = adafruit_mlx90632.REFRESH_2HZ

#
# N8N INTEGRATION
#
def push_to_n8n(history_list):
    try:
        response = requests.post(
            N8N_WEBHOOK_URL,
            json={"history": history_list},
            timeout=7
        )

        if 200 <= response.status_code < 300:
            print(f"[PUSH] Status: {response.status_code}, Response: {response.text}")
            return True
        else:
            print(f"[PUSH] Failed. Status: {response.status_code}, Response: {response.text}")
            return False
        
    except Exception as e:
        print("[PUSH] Error: ", e)
        return False

#
# FILE CONTROL
#
def save_history(history):
    temp_file = HISTORY_FILE + ".tmp"
    try:
        with open(temp_file, "w") as f:
            json.dump(list(history), f)
        # Rename temp tile to actual history file (atomic on Linux)
        os.replace(temp_file, HISTORY_FILE)
        print(f"[HISTORY] Saved {len(history)} records to disk")
    except Exception as e:
        print("[HISTORY] Save error: ", e))

def load_history():
    # Try main history file first
    target_file = HISTORY_FILE
    if not os.path.exists(target_file) and os.path.exists(HISTORY_FILE + ".tmp"):
        # Temp file exists but main file is missing
        target_file = HISTORY_FILE + ".tmp"
    if os.path.exists(target_file):
        try:
            with open(target_file, "r") as f:
                data = json.load(f)
                print(f"[HISTORY] Loaded {len(data)} records from file")
                return deque(data, maxlen=MAX_HISTORY)
        except Exception as e:
            print("[HISTORY] Load error: ", e)
    return deque(maxlen=MAX_HISTORY)

#
# SENSOR POLLING
#
def poll_fir():
    print("[FIR] Polling FIR sensor...")
    ambient_temps = []
    object_temps = []
    i = 0
    while i<5:
        if mlx.data_ready:
            ambient_temp = mlx.ambient_temperature
            object_temp = mlx.object_temperature
            ambient_temps.append(ambient_temp)
            object_temps.append(object_temp)
            i = i+1
            mlx.reset_data_ready
        time.sleep(0.1)

    ambient_avg = statistics.mean([x for x in ambient_temps if not isnan(x)])
    object_avg = statistics.mean([x for x in object_temps if not isnan(x)])

    fir_record = {
        "ambient_temp": ambient_avg,
        "object_temp": object_avg
    }

    return (fir_record)

def poll_camera():
    print("[CAM] Polling camera...")
    dev.dump_eeprom()
    dev.extract_parameters()
    dev.get_frame_data()
    ta = dev.get_ta() - 5.0
    emissivity = 1.0
    to = dev.calculate_to(emissivity, ta)

    max_cam = max(to)
    min_cam = min(to)
    mean_cam = statistics.mean(to)
    std_dev = statistics.stdev(to)

    cam_record = {
        "camera_max": max_cam,
        "camera_avg": mean_cam,
        "camera_min": min_cam,
        "camera_std_dev": std_dev
    }

def poll_sensors():
    print("[SYS] Polling sensors...")
    dt = datetime.now()
    timestamp = time.time()
    fir_record = poll_fir()
    cam_record = poll_camera()
    record = {
        "date": dt.strftime("%Y-%m-%d"),
		"time": dt.strftime("%H:%M:%S"),
        "timestamp": timestamp,
        "unit": {
            "unit id": UNIT_ID
        },
        "fir": fir_record,
        "camera": cam_record
    }

    return record

#
# MAIN CONTROLLER
#
def main():
    """MAIN LOOP"""
    now = time.time()
    history = load_history()

    save_timestamp = now
    push_timestamp = now
    measurement_timestamp = now

    while True:
        now = time.time()
        if(now - measurement_timestamp >= MEASUREMENT_INTERVAL):
            try:
                print("[SYS] Attempting to poll sensors...")
                measurement_timestamp = now
                record = poll_sensors()
                history.append(record)
                print(f"[DATA] New record stored. History length: {len(history)}")
            except Exception as e:
                print("[SYS] Error polling sensors: ", e)

        if(now - save_timestamp >+ SAVE_INTERVAL):
            try:
                print("[SYS] Attempting to save history...")
                save_timestamp = now
                save_history(history)
            except Exception as e:
                print("[SYS] Error saving history: ", e)

        if(now - push_timestamp >= PUSH_INTERVAL):
            try:
                print("[N8N] Attempting to push history...")
                history_list = list(history)
                success = push_to_n8n(history_list)

                if success:
                    push_timestamp = now
                    print("[N8N] Push successful - clearing history")
                    history.clear()
                    save_history(history)
                else:
                    print("[N8N] Push failed")
            except Exception as e:
                print("[SYS] Error pushing data: ", e)

        time.sleep(min(MEASUREMENT_INTERVAL, SAVE_INTERVAL, PUSH_INTERVAL))

if __name__ == "__main__":
    main()