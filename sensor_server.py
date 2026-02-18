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