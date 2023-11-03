import asyncio
import os
from bleak import *
from datetime import datetime
from functools import partial
import numpy as np
import time
import struct
import json

from process import *
from device import Device
from dean_uuid import *

env_sound_model_path = 'models/cnn_12_f32.tflite'

sound_process = SoundProcess()
sound_process.set_env_sound_interpreter(env_sound_model_path)

data_process = DataProcess()

log_process = LogProcess()

async def scan():
    target_devices = []
    devices = await BleakScanner.discover(return_adv=True)

    for dev in devices.keys():
        if dean_uuid_dict['base'] in devices[dev][1].service_uuids:
            target_devices.append(devices[dev][0])
    return target_devices

def disconnected_callback(client):
    print(f'Device {client.address} disconnected')
    
    device = Device.connected_devices.get(client.address, None)
    if device is not None:
        device.remove()

async def ble_main():
    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                if Device.connected_devices.get(dev.address, None) is None:
                    print(dev, "found")

                    device = Device(dev)
                    device.sound_queue = sound_process.get_queue()
                    device.data_queue = data_process.get_queue()

                    await device.ble_client_start(disconnected_callback)

        except Exception as e:
            print(e)
            pass

        await asyncio.sleep(10.0)

if __name__ == "__main__":
    sound_process.start()
    data_process.start()
    log_process.start()

    print("Run Ble Main")
    asyncio.run(ble_main())
