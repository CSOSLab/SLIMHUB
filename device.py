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

    # work: Working mode, raw: Collection mode, both: Both
    mode_default = {
        'grideye': 'work',
        'aat': 'work',
        'environment': 'work',
        'sound': 'work',
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

        self.user_in = False

        self.mode = Device.mode_default
    
    def remove(self):
        self.connected_devices.pop(self.address)
        del self

    def check_room_status(self, data):
        # grideye analysis
        # set active when people comes in
        self.user_in

    # BLE functions ------------------------------------------------------------
    def _ble_notify_callback(self, sender, data):
        data_type = dean_service_lookup[sender.uuid]

        received_time = time.time()

        if dean_service_lookup[sender.service_uuid] == 'sound':
            if not self.sound_queue.full():
                self.sound_queue.put([self.address, received_time, data_type, self.path[str(sender.handle)], data])
        elif dean_service_lookup[sender.service_uuid] == 'grideye':
            self.check_room_status(data)
        else:
            if not self.data_queue.full():
                self.data_queue.put([self.address, received_time, self.path[str(sender.handle)], data])

    def get_service_by_uuid(self, service_uuid):
        for service in self.ble_client.services:
            if service.uuid == service_uuid:
                return service
        return None
    
    def set_service_mode(self, service, mode):
        current_mode = self.mode.get(service, None)
        if current_mode != None:
            current_mode[service] = mode

    async def activate_service(self, service_name):
        data_path = os.path.join(os.getcwd()+"/data", self.location, self.type, self.address)
        
        uuid_dict = dean_uuid_dict.get(service_name, None)
        if uuid_dict != None:
            service_uuid = uuid_dict['service']
            service = self.get_service_by_uuid(service_uuid)

            current_service = dean_service_lookup.get(service.uuid, None)
            if current_service == None:
                return
            
            char_list = []
            for characteristic in service.characteristics:
                current_char = dean_service_lookup.get(characteristic.uuid, None)
                if current_char == None:
                    continue
                char_list.append(characteristic.uuid)
                try:
                    current_path = os.path.join(data_path, current_service)
                    
                    self.path[str(characteristic.handle)] = current_path
                    os.makedirs(current_path, exist_ok=True)

                except Exception as e:
                    print(e)
                    pass
            
            current_mode = self.mode.get(current_service, None)
            if current_mode != None:
                try:
                    if current_mode != 'both':
                        if dean_uuid_dict[current_service][current_mode] in char_list:
                            print('Start notification: '+current_service+':'+current_mode)
                            await self.ble_client.start_notify(dean_uuid_dict[current_service][current_mode], self._ble_notify_callback)
                    else:
                        if dean_uuid_dict[current_service]['work'] in char_list:
                            await self.ble_client.start_notify(dean_uuid_dict[current_service]['work'], self._ble_notify_callback)
                        if dean_uuid_dict[current_service]['raw'] in char_list:
                            await self.ble_client.start_notify(dean_uuid_dict[current_service]['raw'], self._ble_notify_callback)
                except Exception as e:
                    print(e)
                    return

    async def activate_all_services(self):
        for service in self.ble_client.services:
            if service.uuid == DEAN_UUID_CONFIG_SERVICE:
                continue
            
            service_name = dean_service_lookup.get(service.uuid, None)
            if service_name != None:
                await self.activate_service(service_name)

    async def _ble_worker(self, disconnected_callback=None):
        self.ble_client = BleakClient(self.address, disconnected_callback=disconnected_callback)

        # Connect and read device info
        try:
            await self.ble_client.connect()

            service = self.get_service_by_uuid(DEAN_UUID_CONFIG_SERVICE)
            if service is not None:
                self.type = str(await self.ble_client.read_gatt_char(DEAN_UUID_CONFIG_DEVICE_TYPE_CHAR), 'utf-8')
                self.id = str(await self.ble_client.read_gatt_char(DEAN_UUID_CONFIG_DEVICE_NAME_CHAR), 'utf-8')
                self.location = str(await self.ble_client.read_gatt_char(DEAN_UUID_CONFIG_LOCATION_CHAR), 'utf-8')
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
        
        await self.activate_all_services()
    
    async def ble_client_start(self, disconnected_callback=None):
        await self._ble_worker(disconnected_callback)
    
