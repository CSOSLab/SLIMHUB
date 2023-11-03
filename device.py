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

from dean_uuid import *

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

    def get_service_by_uuid(self, service_uuid):
        for service in self.ble_client.services:
            if service.uuid == service_uuid:
                return service
        return None

    async def _ble_worker(self, disconnected_callback=None):
        self.ble_client = BleakClient(self.address, disconnected_callback=disconnected_callback)

        # Connect and read device info
        try:
            await self.ble_client.connect()

            service = self.get_service_by_uuid(dean_uuid_dict['config']['service'])
            if service is not None:
                self.type = str(await self.ble_client.read_gatt_char(dean_uuid_dict['config']['device_type']), 'utf-8')
                self.id = str(await self.ble_client.read_gatt_char(dean_uuid_dict['config']['device_name']), 'utf-8')
                self.location = str(await self.ble_client.read_gatt_char(dean_uuid_dict['config']['location']), 'utf-8')
            else:
                if self.ble_client.is_connected:
                    self.ble_client.disconnect()
                self.remove()
                return

        except Exception as e:
            print(e)
            if self.ble_client.is_connected:
                self.ble_client.disconnect()
            self.remove()
            return

        data_path = os.path.join(os.getcwd()+"/data", self.location, self.type, self.address)
            
        for service in self.ble_client.services:
            if service.uuid == dean_uuid_dict['config']['service']:
                continue

            current_data_type = dean_service_lookup.get(service.uuid, None)
            if current_data_type == None:
                continue

            for characteristic in service.characteristics:
                try:
                    # uuid_split = characteristic.uuid.split("-")

                    # self.location = self.lookup['room'].get(uuid_split[1])
                    # self.type = self.lookup['device_type'].get(uuid_split[2])
                    # current_data_type = self.lookup['data_type'].get(uuid_split[3])

                    current_path = os.path.join(data_path, current_data_type)
                    
                    self.path[str(characteristic.handle)] = current_path
                    print(self.path[str(characteristic.handle)])
                    os.makedirs(current_path, exist_ok=True)

                    # Check data type
                    if current_data_type == "sound":
                        await self.ble_client.start_notify(characteristic.uuid, self._sound_notify_callback)
                    else:
                        await self.ble_client.start_notify(characteristic.uuid, self._data_notify_callback)

                except Exception as e:
                    print(e)
                    pass
        
        if not self.ble_client.is_connected:
            self.remove()
    
    async def ble_client_start(self, disconnected_callback=None):
        await self._ble_worker(disconnected_callback)
    
