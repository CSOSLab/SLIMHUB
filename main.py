import asyncio
import os
from bleak import *
from datetime import datetime
from functools import partial
import numpy as np
import time
import struct
import json
import socket
import select
import argparse
from threading import Thread
from multiprocessing import Manager

from process import *
from device import Device, DeviceManager
from dean_uuid import *

host = 'localhost'
port = 6604
env_sound_model_path = 'models/cnn_12_f32.tflite'

sound_process = SoundProcess()
data_process = DataProcess()
log_process = LogProcess()

manager = DeviceManager()

async def ble_main():
    async def scan():
        target_devices = []
        print('scan start')
        devices = await BleakScanner.discover(return_adv=True, timeout=2)

        for dev in devices.values():
            if DEAN_UUID_BASE_SERVICE in dev[1].service_uuids:
                target_devices.append(dev[0])
        return target_devices
    
    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                if Device.get_device_by_address(dev.address) is None:
                    print(dev, "found")

                    device = Device(dev)
                    device.sound_queue = sound_process.get_queue()
                    device.data_queue = data_process.get_queue()

                    await device.ble_client_start()
                else:
                    print(dev, "reconnected")
                    await device.ble_client_start()

        except Exception as e:
            print(e)
            pass

        await asyncio.sleep(10.0)

async def cli_server():
    def read(s):
        data = ''
        while True:
            block = s.recv(4096)
            if len(block) == 0: return data
            if b'\n' in block:
                block,o = block.split(b'\n', 1)
                data += block.decode()
                return data
            data += block.decode()

    s = socket.socket(socket.AF_INET)
    s.bind((host, port))
    s.listen(5)
    while True:
        sl = select.select([s], [], [], 0.1)
        if len(sl[0]) > 0:
            conn, addr = s.accept()
            data = eval(read(conn))

            await manager.manage(data)
            
        await asyncio.sleep(0.5)

def send_command(cmd, args_dict):
    s = socket.socket(socket.AF_INET)
    try:
        s.connect((host, port))
    except:
        print("Slimhub client is not running")
        sys.exit(1)
    args_dict[cmd].insert(0, cmd)
    s.send(str(args_dict[cmd]).encode())
    
async def async_main():
    ble_task = asyncio.create_task(ble_main())
    manager_task = asyncio.create_task(cli_server())

    await ble_task
    await manager_task

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slimhub service")
    parser.add_argument('-s', '--start', action='store_true', help='main start')
    parser.add_argument('-c', '--config', nargs=3, help='config device')

    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()
    args_dict = vars(args)
    print(args_dict)

    if args.start:
        sound_process.set_env_sound_interpreter(env_sound_model_path)
        sound_process.start()
        data_process.start()
        log_process.start()

        asyncio.run(async_main())
    
    if args.config:
        send_command('config', args_dict)