import multiprocessing as mp
import asyncio
from bleak import *
import os
from datetime import datetime
from functools import partial
import numpy as np
import time
import struct
import json

import sound_process as snd
import tensorflow_lite as tflite

class Device:
    connected_devices = {}

    lookup = {
        'room': {
            '0001': 'KITCHEN',
            '0002': 'LIVING',
            '0003': 'ROOM',
            '0004': 'TOILET',
            '0005': 'HOME_ENTRANCE',
            '0006': 'LIVING_ENTRANCE',
            '0007': 'KITCHEN_ENTRANCE',
            '0008': 'STAIR',
            'ff01': 'RTLAB501',
            'ff02': 'RTLAB502',
            'ff03': 'RTLAB503',
            'ffff': 'TEST'
        },
        'device_type': {
            '0001': 'ADL_DETECTOR',
            '0002': 'THINGY53',
            '0003': 'ATT'
        },
        'data_type': {
            '0001': 'RAW',
            '0002': 'GRIDEYE_ACTION',
            '0003': 'ENVIRONMENT',
            '0004': 'SOUND',
            '0005': 'AAT_ACTION'
        }
    }

    def __init__(self, dev):
        self.connected_devices[dev.address] = self
        
        self.name = dev.name
        self.address = dev.address
        self.id = ''
        self.type = '' 
        self.location = ''
        
        self.path = {}

        self.ble_client = None

        self.sound_queue = None
        self.data_queue = None
    
    def remove(self):
        self.connected_devices.pop(self.address)
        del self

        # BLE functions ------------------------------------------------------------
    def _data_notify_callback(self, sender, data):
        received_time = time.time()
        if not self.data_queue.full():
            self.data_queue.put([self.address, received_time, self.path[str(sender.handle)], data])
    
    def _sound_notify_callback(self, sender, data):
        received_time = time.time()
        if not self.sound_queue.full():
            self.sound_queue.put([self.address, received_time, self.path[str(sender.handle)], data])

    async def _ble_worker(self, disconnected_callback=None):
        self.ble_client = BleakClient(self.address, disconnected_callback=disconnected_callback)

        try:
            await self.ble_client.connect()

            for service in self.ble_client.services:
                for characteristic in service.characteristics:
                    try:
                        path = os.getcwd()+"/data"

                        uuid_split = characteristic.uuid.split("-")

                        self.location = self.lookup['room'].get(uuid_split[1])
                        self.type = self.lookup['device_type'].get(uuid_split[2])
                        current_data_type = self.lookup['data_type'].get(uuid_split[3])

                        path = os.path.join(path, self.location, self.type, self.address, current_data_type)
                        
                        self.path[str(characteristic.handle)] = path
                        print(self.path[str(characteristic.handle)])
                        os.makedirs(path, exist_ok=True)

                        # Check data type
                        if current_data_type == "SOUND":
                            await self.ble_client.start_notify(characteristic.uuid, self._sound_notify_callback)
                        else:
                            await self.ble_client.start_notify(characteristic.uuid, self._data_notify_callback)

                    except Exception as e:
                        print(e)
                        pass          

        except Exception as e:
            print(e)
            pass

        finally:
            if not self.ble_client.is_connected:
                self.remove()
    
    async def ble_client_start(self, disconnected_callback=None):
        await self._ble_worker(disconnected_callback)
    
