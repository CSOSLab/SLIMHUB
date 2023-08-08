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
from device import Device, DeviceManager
import sysv_ipc
from msgq import Msgq

manager = DeviceManager()

env_sound_model_path = 'models/sample_sound_model.tflite'

async def scan():
    target_devices = []
    devices = await BleakScanner.discover()
    # print(devices)
    # print(devices)
    for dev in devices:
        if dev.name.split("_")[0] == 'ADL-TEST':
            # if dev.address=="DA:A1:DE:9D:DB:B1":
                target_devices.append(dev)
    return target_devices

def disconnected_callback(client):
    print(f'Device {client.address} disconnected')
    
    device = manager.connected_devices.get(client.address, None)
    if device is not None:
        manager.remove_device(device)

async def ble_main():
    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                if manager.connected_devices.get(dev.address, None) is None:
                    print(dev, "found")

                    device = Device(dev)
                    manager.add_device(device)

                    if not await device.ble_client_start(disconnected_callback):
                        manager.remove_device(device)

        except Exception as e:
            print(e)
            pass

        await asyncio.sleep(10.0)

if __name__ == "__main__":
    print("Mqtt On")

    manager.mqtt = Mqtt(
        ip="155.230.186.52",
        port=1883,
        id="csosMember",
        passwd="csos!1234",
        sh_id="HMK0H001")
    
    manager.mqtt.connect()

    manager.msgq = Msgq(6604, sysv_ipc.IPC_CREAT)

    manager.set_env_sound_interpreter(env_sound_model_path)

    manager.process_start_all()

    print("Run Ble Main")
    asyncio.run(ble_main())
