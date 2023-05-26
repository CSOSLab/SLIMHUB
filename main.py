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

device_list = []

env_sound_model_path = 'models/sample_sound_model.tflite'

async def scan():
    target_devices = []
    devices = await BleakScanner.discover()
    # print(devices)
    # print(devices)
    for dev in devices:
        if dev.name.split("_")[0] == 'ADL':
            target_devices.append(dev)
    return target_devices

def search_device(address):
    for device in device_list:
        if device.dev.address == address:
            return device_list.index(device)
    return None

def disconnected_callback(client):
    print(f'Device {client.address} disconnected, reason')
    
    index = search_device(client.address)
    if index is not None:
        device = device_list.pop(index)
        device.terminate_all()
        del device

async def ble_main():
    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                index = search_device(dev.address)
                if index is None:
                # if str(dev) not in task_list:
                    print(dev, "find")

                    device = Device(dev)
                    device.set_env_sound_interpreter(env_sound_model_path)

                    await device.ble_client_start(disconnected_callback)
                    device_list.append(device)
        except Exception as e:
            print(e)
            pass

        # await asyncio.sleep(10.0)

if __name__ == "__main__":
    print("Mqtt On")
    Device.mqtt = Mqtt("155.230.186.52", 1883, "csosMember", "csos!1234", "HMK0H001")
    Device.mqtt.connect()
    Device.msgq = Msgq(6604, sysv_ipc.IPC_CREAT)

    print("Run Ble Main")
    asyncio.run(ble_main())
