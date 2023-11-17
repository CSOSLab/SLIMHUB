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
import struct

from dean_uuid import *

class Device:
    connected_devices = {}

    # work: Working mode, data: Collection mode, both: Both
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
        value = struct.unpack('B', data[0:1])[0]
        print(value//10, value%10)

    # BLE functions ------------------------------------------------------------
    def _ble_notify_callback(self, sender, data):
        data_type = dean_service_lookup[sender.uuid]

        received_time = time.time()

        if dean_service_lookup[sender.service_uuid] == 'sound':
            if not self.sound_queue.full():
                self.sound_queue.put([self.address, received_time, data_type, self.path[str(sender.handle)], data])
        elif dean_service_lookup[sender.service_uuid] == 'grideye':
            self.check_room_status(data)
            if not self.data_queue.full():
                self.data_queue.put([self.address, received_time, self.path[str(sender.handle)], data])
        else:
            if not self.data_queue.full():
                self.data_queue.put([self.address, received_time, self.path[str(sender.handle)], data])
    
    def _ble_disconnected_callback(self, client):
        print(f'Device {client.address} disconnected')
        # self.remove()

    def get_service_by_uuid(self, service_uuid):
        for service in self.ble_client.services:
            if service.uuid == service_uuid:
                return service
        return None
    
    def get_service_by_name(self, service_name):
        uuid_dict = dean_uuid_dict.get(service_name, None)
        if uuid_dict != None:
            return self.get_service_by_uuid(uuid_dict['service'])
        return None
    
    def set_service_mode(self, service_name, mode):
        if mode not in ['work', 'data']:
            print("invalid mode")
            return
        current_mode = self.mode.get(service_name, None)
        if current_mode != None:
            current_mode[service_name] = mode
        else:
            print("invalid service")
    
    async def activate_service(self, service):
        current_service = dean_service_lookup[service.uuid]
        char_list = []
        for characteristic in service.characteristics:
            char_list.append(characteristic.uuid)
        
        current_mode = self.mode.get(current_service, None)
        if current_mode != None:
            try:
                if dean_uuid_dict[current_service][current_mode] in char_list:
                    print('Start notification: '+current_service+':'+current_mode)
                    await self.ble_client.start_notify(dean_uuid_dict[current_service][current_mode], self._ble_notify_callback)
            except Exception as e:
                print(e)
                return
    
    async def deactivate_service(self, service):
        for characteristic in service.characteristics:
            current_char = dean_service_lookup.get(characteristic.uuid, None)
            if current_char == None:
                continue
            try:
                await self.ble_client.stop_notify(characteristic.uuid)
            except:
                pass

    async def init_service(self, service):
        data_path = os.path.join(os.getcwd()+"/data", self.location, self.type, self.address)

        service_name = dean_service_lookup.get(service.uuid, None)
        if service_name == None:
            return
        
        char_list = []
        for characteristic in service.characteristics:
            current_char = dean_service_lookup.get(characteristic.uuid, None)
            if current_char == None:
                continue
            char_list.append(characteristic.uuid)
            try:
                current_path = os.path.join(data_path, service_name, current_char)
                
                self.path[str(characteristic.handle)] = current_path
                os.makedirs(current_path, exist_ok=True)

            except Exception as e:
                print(e)
                pass

        await self.activate_service(service)

    async def init_all_services(self):
        for service in self.ble_client.services:
            if service.uuid == DEAN_UUID_CONFIG_SERVICE:
                continue

            await self.init_service(service)

    async def _ble_worker(self):
        self.ble_client = BleakClient(self.address, disconnected_callback=self._ble_disconnected_callback)

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
        
        await self.init_all_services()
    
    async def ble_client_start(self):
        await self._ble_worker()