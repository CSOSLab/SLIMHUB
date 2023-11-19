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

    enable_default = {
        'grideye': ['prediction'],
        'aat': ['action'],
        'environment': ['send'],
        'sound': ['processed'],
    }

    def __init__(self, dev):
        self.connected_devices[dev.address] = self
        
        self.config_dict = {
            'address': dev.address,
            'type': dev.name,
            'name': '',
            'location': '',
        }

        self.path = {}

        self.ble_client = None

        self.sound_queue = None
        self.data_queue = None

        self.user_in = False

        self.enable = Device.enable_default
    
    def remove(self):
        self.connected_devices.pop(self.config_dict['address'])
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
                self.sound_queue.put([self.config_dict['address'], received_time, data_type, self.path[str(sender.handle)], data])
        elif dean_service_lookup[sender.service_uuid] == 'grideye':
            self.check_room_status(data)
            if not self.data_queue.full():
                self.data_queue.put([self.config_dict['address'], received_time, self.path[str(sender.handle)], data])
        else:
            if not self.data_queue.full():
                self.data_queue.put([self.config_dict['address'], received_time, self.path[str(sender.handle)], data])
    
    def _ble_disconnected_callback(self, client):
        print(f'Device {client.address} disconnected')
        # self.remove()

    def get_service_by_uuid(self, service_uuid):
        for service in self.ble_client.services:
            if service.uuid == service_uuid:
                return service
        return None
    
    def get_service_by_name(self, service_name):
        char_dict = dean_service_dict.get(service_name, None)
        if char_dict != None:
            return self.get_service_by_uuid(char_dict['service'])
        return None
    
    async def activate_characteristic(self, service_name, char_name):
        service = self.get_service_by_name(service_name)
        if service is not None:
            char_dict = dean_service_dict.get(service_name)
            char_uuid = char_dict.get(char_name, None)
            if char_uuid is not None:
                print('Start notification: '+service_name+':'+char_name)
                try:
                    await self.ble_client.start_notify(char_uuid, self._ble_notify_callback)
                except:
                    print(service_name, char_name, 'activation failed')
                    return 
    
    async def deactivate_characteristic(self, service_name, char_name):
        service = self.get_service_by_name(service_name)
        if service is not None:
            char_dict = dean_service_dict.get(service_name)
            char_uuid = char_dict.get(char_name, None)
            if char_uuid is not None:
                await self.ble_client.stop_notify(char_uuid, self._ble_notify_callback)

    async def activate_service(self, service_name):
        service = self.get_service_by_name(service_name)
        char_list = []
        for characteristic in service.characteristics:
            char_list.append(characteristic.uuid)
        
        enable_list = self.enable.get(service_name, None)
        if enable_list != None:
            for char_name in enable_list:
                await self.activate_characteristic(service_name, char_name)
    
    async def deactivate_service(self, service_name):
        service = self.get_service_by_name(service_name)
        for characteristic in service.characteristics:
            char_name = dean_service_lookup.get(characteristic.uuid, None)
            if char_name == None:
                continue
            try:
                await self.ble_client.stop_notify(characteristic.uuid)
            except:
                pass

    async def init_service(self, service_name):
        data_path = os.path.join(os.getcwd()+"/data", self.config_dict['location'], self.config_dict['type'], self.config_dict['address'])

        service = self.get_service_by_name(service_name)

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

        await self.activate_service(service_name)

    async def init_all_services(self):
        for service in self.ble_client.services:
            if service.uuid == DEAN_UUID_CONFIG_SERVICE:
                continue

            service_name = dean_service_lookup.get(service.uuid, None)

            await self.init_service(service_name)

    async def _connect_device(self):
         # Connect and read device info
        try:
            await self.ble_client.connect()

            service = self.get_service_by_uuid(DEAN_UUID_CONFIG_SERVICE)
            if service is not None:
                self.config_dict['name'] = str(await self.ble_client.read_gatt_char(DEAN_UUID_CONFIG_NAME_CHAR), 'utf-8')
                self.config_dict['location'] = str(await self.ble_client.read_gatt_char(DEAN_UUID_CONFIG_LOCATION_CHAR), 'utf-8')
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

    async def _ble_worker(self):
        self.ble_client = BleakClient(self.config_dict['address'], disconnected_callback=self._ble_disconnected_callback)

        await self._connect_device()
        await self.init_all_services()
    
    async def ble_client_start(self):
        await self._ble_worker()