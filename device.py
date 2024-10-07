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
import logging

from dean_uuid import *

connected_devices = {}

def get_device_by_address(address):
    return connected_devices.get(address, None)

class DeviceError(Exception):
    pass
        
class Device:
    enable_default = {
        'inference': ['send']
    }

    def __init__(self, dev):
        connected_devices.update({dev.address: self})

        self.model_dir = "programdata/models/"+dev.address
        os.makedirs(self.model_dir, exist_ok=True)

        self.config_dict = {
            'address': dev.address,
            'type': dev.name,
            'name': '',
            'location': '',
        }

        self.ble_client = None

        self.manager_queue = None
        self.sound_queue = None
        self.data_queue = None

        self.user_in = False

        self.enable = Device.enable_default

        self.is_connected = False
    
    def __repr__(self):
        return f"{self.__class__.__name__}: {self.config_dict['address']}, {self.config_dict['type']}, {self.config_dict['name']}, {self.config_dict['location']}"
    
    async def remove(self):
        try:
            await self.ble_client.disconnect()
        except:
            pass
        try:
            connected_devices.pop(self.config_dict['address'])
        except:
            pass
        finally:
            del self
        
    def check_room_status(self, data):
        # grideye analysis
        # set active when people comes in
        value = struct.unpack('B', data[0:1])[0]
        # print(value//10, value%10)

    # BLE functions ------------------------------------------------------------
    def _ble_notify_callback(self, sender, data):
        service_name = dean_service_lookup[sender.service_uuid]
        char_name = dean_service_lookup[sender.uuid]

        received_time = time.time()

        if service_name == 'sound':
            if not self.sound_queue.full():
                self.sound_queue.put([self.config_dict['location'], self.config_dict['type'], self.config_dict['address'], service_name, char_name, received_time, data])
        elif service_name == 'inference':
            self.check_room_status(data)
            if not self.data_queue.full():
                self.data_queue.put([self.config_dict['location'], self.config_dict['type'], self.config_dict['address'], service_name, char_name, received_time, data])
    
    def _ble_disconnected_callback(self, client):
        logging.info('%s: %s disconnected', client.address, self.config_dict['type'])
        self.is_connected = False

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
    
    async def config_device(self, target, data):
        config_path = os.path.dirname(os.path.realpath(__file__))+"/programdata/config"
        os.makedirs(config_path, exist_ok=True)

        file_path = os.path.join(config_path, self.config_dict['address']+'.json')
        if target in self.config_dict:
            self.config_dict[target] = data
        else:
            return
        
        char_uuid = dean_service_dict['config'][target]
        with open(file_path, 'w') as save:
            json.dump(self.config_dict, save, indent=4)
        await self.ble_client.write_gatt_char(char_uuid, bytearray(data, 'utf-8'))

    async def load_config(self):
        config_path = os.path.dirname(os.path.realpath(__file__))+"/programdata/config"
        os.makedirs(config_path, exist_ok=True)

        file_path = os.path.join(config_path, self.config_dict['address']+'.json')
        if os.path.isfile(file_path):
            with open(file_path) as f:
                json_data = json.load(f)
                self.config_dict['name'] = json_data['name']
                self.config_dict['location'] = json_data['location']
            try:
                await self.ble_client.write_gatt_char(DEAN_UUID_CONFIG_NAME_CHAR, bytearray(self.config_dict['name'], 'utf-8'))
                await self.ble_client.write_gatt_char(DEAN_UUID_CONFIG_LOCATION_CHAR, bytearray(self.config_dict['location'], 'utf-8'))
                return True
            except Exception as e:
                logging.warning(e)
                return False
        else:
            return False
    
    def save_config(self):
        config_path = os.path.dirname(os.path.realpath(__file__))+"/programdata/config"
        os.makedirs(config_path, exist_ok=True)

        file_path = os.path.join(config_path, self.config_dict['address']+'.json')
        with open(file_path, 'w') as save:
            json.dump(self.config_dict, save, indent=4)
            
    async def activate_characteristic(self, service_name, char_name):
        service = self.get_service_by_name(service_name)
        if service is not None:
            char_dict = dean_service_dict.get(service_name)
            char_uuid = char_dict.get(char_name, None)
            if char_uuid is not None:
                try:
                    await self.ble_client.start_notify(char_uuid, self._ble_notify_callback)
                    logging.info('%s: Characteristic %s %s %s', self.config_dict['address'], service_name, char_name, 'enabled')
                    return True
                except:
                    logging.info('%s: Characteristic %s %s %s', self.config_dict['address'], service_name, char_name, 'activation failed')
                    return False

    async def deactivate_characteristic(self, service_name, char_name):
        service = self.get_service_by_name(service_name)
        if service is not None:
            char_dict = dean_service_dict.get(service_name)
            char_uuid = char_dict.get(char_name, None)
            if char_uuid is not None:
                try:
                    await self.ble_client.stop_notify(char_uuid)
                    logging.info('%s: Characteristic %s %s %s', self.config_dict['address'], service_name, char_name, 'disabled')
                    return True
                except:
                    logging.info('%s: Characteristic %s %s %s', self.config_dict['address'], service_name, char_name, 'deactivation failed')
                    return False

    async def activate_service(self, service_name):
        service = self.get_service_by_name(service_name)

        char_list = []
        for characteristic in service.characteristics:
            current_char = dean_service_lookup.get(characteristic.uuid, None)
            if current_char == None:
                continue
            char_list.append(characteristic.uuid)
        
        enable_list = self.enable.get(service_name, None)
        if enable_list != None:
            for char_name in enable_list:
                try:
                    await self.activate_characteristic(service_name, char_name)
                except Exception as e:
                    logging.warning(e)
                    pass
                await asyncio.sleep(0.1)

    async def deactivate_service(self, service_name):
        service = self.get_service_by_name(service_name)
        for characteristic in service.characteristics:
            char_name = dean_service_lookup.get(characteristic.uuid, None)
            if char_name == None:
                continue
            try:
                await self.ble_client.stop_notify(characteristic.uuid)
            except Exception as e:
                logging.warning(e)
                pass

    async def init_services(self):
        try:
            for service in self.ble_client.services:
                if service.uuid == DEAN_UUID_CONFIG_SERVICE:
                    continue

                service_name = dean_service_lookup.get(service.uuid, None)
                if service_name is not None:
                    await self.activate_service(service_name)
                await asyncio.sleep(0.1)
        except Exception as e:
            logging.warning(e)
            raise DeviceError("Service initialization failed")

    async def sync_current_time(self):
        now = datetime.now()

        year = now.year
        month = now.month
        day = now.day
        hours = now.hour
        minutes = now.minute
        seconds = now.second
        day_of_week = now.isoweekday() % 7
        exact_time_256 = 0
        adjust_reason = 0

        format_string = '<HBBBBBBBB'

        packed_data = struct.pack(format_string, year, month, day, hours, minutes, seconds, day_of_week, exact_time_256, adjust_reason)

        await self.ble_client.write_gatt_char(DEAN_UUID_CTS_CURRENT_TIME_CHAR, packed_data)

    async def _connect_device(self):
         # Connect and read device info
        try:
            await self.ble_client.connect()
            await asyncio.sleep(0.1)
            
            config_service = self.get_service_by_uuid(DEAN_UUID_CONFIG_SERVICE)
            
            if not await self.load_config():
                if config_service is not None:
                    self.config_dict['name'] = str(await self.ble_client.read_gatt_char(DEAN_UUID_CONFIG_NAME_CHAR), 'utf-8')
                    self.config_dict['location'] = str(await self.ble_client.read_gatt_char(DEAN_UUID_CONFIG_LOCATION_CHAR), 'utf-8')
                    self.save_config()
                else:
                    raise DeviceError("Device configuration failed")
            
            cts = self.get_service_by_uuid(DEAN_UUID_CTS_SERVICE_UUID)
            if cts is not None:
                await self.sync_current_time()

        except Exception as e:
            logging.warning(e)
            raise DeviceError("Device connection failed")

    async def _ble_worker(self):
        self.ble_client = BleakClient(self.config_dict['address'], disconnected_callback=self._ble_disconnected_callback)
        try:
            await self._connect_device()
            self.is_connected = True
            await self.init_services()
            return True
        
        except DeviceError as e:
            logging.warning(e)
            await self.remove()
            return False
            
    async def ble_client_start(self):
        return await self._ble_worker()

class DeviceManager:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def process_command(self, commands):
        cmd = commands[0]
        if len(commands) > 1:
            address = commands[1]
            device = get_device_by_address(address)

            if device is None:
                return str(address)+' is not registered'.encode()
            
        if cmd == 'config':
            await device.config_device(commands[2], commands[3])
            return_msg = f"address: {device.config_dict['address']}, type: {device.config_dict['type']}, name: {device.config_dict['name']}, location: {device.config_dict['location']}"
            return return_msg.encode()

        elif cmd == 'service':
            if commands[2] == 'enable':
                if await device.activate_characteristic(commands[3], commands[4]):
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} enabled".encode()
                else:
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} enable failed".encode()
            elif commands[2] == 'disable':
                if await device.deactivate_characteristic(commands[3], commands[4]):
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} disabled".encode()
                else:
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} disable failed".encode()
            else:
                return "Argment 2 must be \'enable\' or \'disable\'".encode()
        
        elif cmd == 'list':
            return_msg = f"{'Address':<20}{'Type':<10}{'Name':<15}{'Location':<15}{'Connected':<10}\n"
            for value in connected_devices.values():
                return_msg += f"{value.config_dict['address']:<20}{value.config_dict['type']:<10}{value.config_dict['name']:<15}{value.config_dict['location']:<15}{value.is_connected:<10}\n"
            return return_msg.encode()

        elif cmd == 'apply':
            for value in connected_devices.values():
                await value.load_config()
                await asyncio.sleep(0.1)
            return "Config data applied".encode()

    def get_queue(self):
        return self.queue
    
    async def manager_main(self):
        while True:
            try:
                data = self.queue.get_nowait()
            except:
                await asyncio.sleep(1)