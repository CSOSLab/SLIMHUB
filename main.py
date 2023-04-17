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

async def scan():
    target_devices = []
    devices = await BleakScanner.discover()
    # print(devices)
    # print(devices)
    for dev in devices:
        if dev.name.split("_")[0] == 'ADL':
            target_devices.append(dev)
    return target_devices

def search_address(address):
    for device in device_list:
        if device.dev.address == address:
            return device_list.index(device)
    return None

def disconnected_callback(client):
    print(f'Device {client.address} disconnected, reason')
    
    index = search_address(client.address)
    if index is not None:
        device = device_list.pop(index)
        device.process.terminate()
        del device

async def ble_main():
    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                index = search_address(dev.address)
                if index is None:
                # if str(dev) not in task_list:
                    print(dev, "find")

                    device = Device(dev)
                    await device.ble_client_start(disconnected_callback)
                    
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
