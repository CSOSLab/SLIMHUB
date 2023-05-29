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
import sysv_ipc
from msgq import Msgq

env_sound_model_path = 'models/sample_sound_model.tflite'

async def scan():
    target_devices = []
    devices = await BleakScanner.discover()
    # print(devices)
    # print(devices)
    for dev in devices:
        if dev.name.split("_")[0] == 'ADL':
            # if dev.address=="DA:A1:DE:9D:DB:B1":
                target_devices.append(dev)
    return target_devices

def disconnected_callback(client):
    print(f'Device {client.address} disconnected')
    
    device = Device.manager.connected_devices.get(client.address, None)
    if device is not None:
        device.remove()

async def ble_main():
    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                if Device.manager.connected_devices.get(dev.address, None) is None:
                    print(dev, "found")

                    device = Device(dev)

                    await device.ble_client_start(disconnected_callback)

        except Exception as e:
            print(e)
            pass

        await asyncio.sleep(10.0)

if __name__ == "__main__":
    print("Mqtt On")
    Device.manager.mqtt = Mqtt("155.230.186.52", 1883, "csosMember", "csos!1234", "HMK0H001")
    Device.manager.mqtt.connect()
    Device.manager.msgq = Msgq(6604, sysv_ipc.IPC_CREAT)

    Device.manager.set_env_sound_interpreter(env_sound_model_path)

    Device.manager.process_start_all()

    print("Run Ble Main")
    asyncio.run(ble_main())
