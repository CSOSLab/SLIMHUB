import asyncio
import os
from bleak import *
from datetime import datetime
from functools import partial
import numpy as np
import time
import struct
import json

from mqtt import Mqtt
from device import Device

device_list = []

labels = ['speech' 'microwave' 'vacuuming' 'tv' 'eating' 'drop' 'smoke_extractor'
          'cooking' 'dish_clanging' 'peeing' 'chopping' 'water_flowing'
          'toilet_flushing' 'walking' 'brushing_teeth']
sound_model_path = "models/sample_sound_model.tflite"

async def scan():
    target_devices = []
    devices = await BleakScanner.discover()
    # print(devices)
    # print(devices)
    for dev in devices:
        if dev.name.split("_")[0] == 'ADL-CHLEE':
            target_devices.append(dev)
    return target_devices

def disconnected_callback(client):
    print(f'Device {client.address} disconnected, reason')
    print(client)

async def ble_main():
    task_list = []

    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                if str(dev) not in task_list:
                    # print(dev, "find")

                    device = Device(dev)
                    await device.ble_client_start(disconnected_callback)
                    
                    task_list.append(str(dev))
                    device_list.append(device)

        except:
            pass

        await asyncio.sleep(10.0)

if __name__ == "__main__":
    print("Mqtt On")
    Device.mqtt = Mqtt("155.230.186.52", 1883, "csosMember", "csos!1234", "HMK0H001")
    Device.mqtt.connect()

    print("Run Ble Main")
    asyncio.run(ble_main())
