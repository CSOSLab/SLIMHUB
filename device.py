import multiprocessing as mp
import subprocess
import asyncio
from bleak import *
import os
from datetime import datetime
from functools import partial
import numpy as np
import time
import struct
import json
import logging

from dean_uuid import *
from packet import *
from unitspace_manager import UnitspaceManager

connected_devices = {}

def get_device_by_address(address):
    return connected_devices.get(address, None)

class DeviceError(Exception):
    pass

unitspace_manager = UnitspaceManager()

class Device:
    sound_classlist = [
        'background',
        'hitting',
        'speech_tv',
        'air_appliances',
        'brushing',
        'peeing',
        'flushing',
        'flush_end',
        'microwave',
        'cooking',
        'watering_low',
        'watering_high',
    ]

    service_enable_default = {
        'sound': ['model'],
        'grideye': ['prediction'],
        'inference': ['rawdata', 'predict', 'debugstr']
    }
    model_chunk_size = 128

    def __init__(self, dev):
        # Update connected device dictionary
        connected_devices.update({dev.address: self})

        self.config_dict = {
            'address': dev.address,
            'type': dev.name,
            'name': '',
            'location': '',
        }
        self.is_connected = False

        self.ble_client = None
        self.manager_queue = None
        self.sound_queue = None
        self.data_queue = None
        self.unitspace_queue = None
        self.log_queue = None
        
        # Sound model management
        self.model_dir = "programdata/models/" + dev.address
        os.makedirs(self.model_dir, exist_ok=True)
        self.model_path = os.path.join("programdata", "models", dev.address, dev.address + ".tflite")
        self.sending_model = False
        self.model_seq = 0
        self.model_size = 0
        if os.path.isfile(self.model_path):
            with open(self.model_path, 'rb') as f:
                self.model_size = len(f.read())
        self.collecting_feature = False

        self.user_in = False
        
        self.enable = Device.service_enable_default
    
    def __repr__(self):
        return f"{self.__class__.__name__}: {self.config_dict['address']}, {self.config_dict['type']}, {self.config_dict['name']}, {self.config_dict['location']}"
    
    async def remove(self):
        try:
            await self.ble_client.disconnect()
        except Exception as e:
            logging.warning("Error during disconnect: %s", e)
        try:
            address = self.config_dict.get("address")
            if address in connected_devices:
                connected_devices.pop(address, None)
        except Exception as e:
            logging.warning("Error during device removal: %s", e)
        # finally:
        #     del self
        
    def check_room_status(self, data):
        value = struct.unpack('B', data[0:1])[0]
    
    def _ble_notify_callback(self, sender, data):
        service_name = dean_service_lookup[sender.service_uuid]
        char_name = dean_service_lookup[sender.uuid]
        received_time = time.time()
        
        if service_name == 'sound':
            if char_name == 'model':
                recv_packet = ModelPacket.unpack(data)
                if recv_packet.cmd == MODEL_UPDATE_CMD_START:
                    if not self.sending_model:
                        self.sending_model = True
                        asyncio.create_task(self.model_send_worker())
                elif recv_packet.cmd == MODEL_UPDATE_CMD_DATA:
                    recv_packet = ModelAckPacket.unpack(data)
                    self.model_seq = recv_packet.seq + 1
                    asyncio.create_task(self.model_send_worker())
                elif recv_packet.cmd == MODEL_UPDATE_CMD_END:
                    logging.info('%s: Model update completed', self.config_dict['address'])
                    self.sending_model = False
                    self.model_seq = 0
                elif recv_packet.cmd == MODEL_UPDATE_CMD_FAIL:
                    logging.info('%s: Model update failed', self.config_dict['address'])
                    self.sending_model = False
                    self.model_seq = 0

                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_START:
                    self.collecting_feature = True
                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_DATA:
                    if not self.sound_queue.full():
                        self.sound_queue.put([self.config_dict['location'], self.config_dict['type'],
                                               self.config_dict['address'], service_name, char_name,
                                               received_time, data])
                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_FINISH:
                    if not self.sound_queue.full():
                        self.sound_queue.put([self.config_dict['location'], self.config_dict['type'],
                                               self.config_dict['address'], service_name, char_name,
                                               received_time, data])
                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_END:
                    self.collecting_feature = False

        elif service_name == 'inference':
            if char_name == 'rawdata':
                self.check_room_status(data)
                if not self.data_queue.full():
                    self.data_queue.put([self.config_dict['location'], self.config_dict['type'],
                                         self.config_dict['address'], service_name, char_name,
                                         received_time, data])
                # if not self.unitspace_queue.full():
                fmt = '<BBBfffffB20b'
                unpacked_data = struct.unpack(fmt, data)
                unpacked_data_list = list(unpacked_data)
                if unpacked_data_list[0] == 1:
                    # Unitspace management start
                    asyncio.create_task(unitspace_manager.unitspace_existence_estimation(self.config_dict['location'], self.config_dict['type'],
                                                self.config_dict['address'], service_name, char_name,
                                                received_time, unpacked_data_list))
                    # self.unitspace_queue.put([self.config_dict['location'], self.config_dict['type'],
                    #                           self.config_dict['address'], service_name, char_name,
                    #                           received_time, unpacked_data_list])
            elif char_name == 'predict':
                print("WIP : mqtt service required for handling inference result")   
            elif char_name == 'debugstr':
                if not self.data_queue.full():
                    self.data_queue.put([self.config_dict['location'], self.config_dict['type'],
                                         self.config_dict['address'], service_name, char_name,
                                         received_time, data])
                if not self.log_queue.full():
                    self.log_queue.put([self.config_dict['location'], self.config_dict['type'],
                                         self.config_dict['address'], service_name, char_name,
                                         received_time, data])
        
    def _ble_disconnected_callback(self, client):
        logging.info('%s: %s disconnected', client.address, self.config_dict['type'])
        self.model_seq = 0
        self.sending_model = False
        self.is_connected = False
    
    def get_service_by_uuid(self, service_uuid):
        for service in self.ble_client.services:
            if service.uuid == service_uuid:
                return service
        return None
    
    def get_service_by_name(self, service_name):
        char_dict = dean_service_dict.get(service_name, None)
        if char_dict is not None:
            return self.get_service_by_uuid(char_dict['service'])
        return None

    async def config_device(self, target, data):
        config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "config")
        os.makedirs(config_path, exist_ok=True)
        file_path = os.path.join(config_path, self.config_dict['address'] + '.json')
        if target in self.config_dict:
            self.config_dict[target] = data
        else:
            return
        char_uuid = dean_service_dict['config'][target]
        with open(file_path, 'w') as save:
            json.dump(self.config_dict, save, indent=4)
        await self.ble_client.write_gatt_char(char_uuid, bytearray(data, 'utf-8'))

    async def load_config(self):
        config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "config")
        os.makedirs(config_path, exist_ok=True)
        file_path = os.path.join(config_path, self.config_dict['address'] + '.json')
        if os.path.isfile(file_path):
            with open(file_path) as f:
                json_data = json.load(f)
                self.config_dict['name'] = json_data['name']
                self.config_dict['location'] = json_data['location']
            try:
                await self.ble_client.write_gatt_char(DEAN_UUID_CONFIG_NAME_CHAR,
                                                      bytearray(self.config_dict['name'], 'utf-8'))
                await self.ble_client.write_gatt_char(DEAN_UUID_CONFIG_LOCATION_CHAR,
                                                      bytearray(self.config_dict['location'], 'utf-8'))
                return True
            except Exception as e:
                logging.warning(e)
                return False
        else:
            return False
    
    def save_config(self):
        config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "config")
        os.makedirs(config_path, exist_ok=True)
        file_path = os.path.join(config_path, self.config_dict['address'] + '.json')
        with open(file_path, 'w') as save:
            json.dump(self.config_dict, save, indent=4)

    async def reset_device(self):
        char_uuid = dean_service_dict['base']['reset']
        await self.ble_client.write_gatt_char(char_uuid, True)
            
    async def activate_characteristic(self, service_name, char_name):
        service = self.get_service_by_name(service_name)
        if service is not None:
            char_dict = dean_service_dict.get(service_name)
            char_uuid = char_dict.get(char_name, None)
            if char_uuid is not None:
                try:
                    await self.ble_client.start_notify(char_uuid, self._ble_notify_callback)
                    logging.info('%s: Characteristic %s %s %s',
                                 self.config_dict['address'], service_name, char_name, 'enabled')
                    return True
                except Exception as e:
                    logging.info('%s: Characteristic %s %s %s - %s',
                                 self.config_dict['address'], service_name, char_name, 'activation failed', e)
                    return False

    async def deactivate_characteristic(self, service_name, char_name):
        service = self.get_service_by_name(service_name)
        if service is not None:
            char_dict = dean_service_dict.get(service_name)
            char_uuid = char_dict.get(char_name, None)
            if char_uuid is not None:
                try:
                    await self.ble_client.stop_notify(char_uuid)
                    logging.info('%s: Characteristic %s %s %s',
                                 self.config_dict['address'], service_name, char_name, 'disabled')
                    return True
                except Exception as e:
                    logging.info('%s: Characteristic %s %s %s - %s',
                                 self.config_dict['address'], service_name, char_name, 'deactivation failed', e)
                    return False

    async def activate_service(self, service_name):
        service = self.get_service_by_name(service_name)
        if service is None:
            logging.warning("%s: Service %s not found", self.config_dict['address'], service_name)
            return
        char_list = []
        for characteristic in service.characteristics:
            current_char = dean_service_lookup.get(characteristic.uuid, None)
            if current_char is None:
                continue
            char_list.append(characteristic.uuid)
        enable_list = self.enable.get(service_name, None)
        if enable_list is not None:
            for char_name in enable_list:
                try:
                    await self.activate_characteristic(service_name, char_name)
                except Exception as e:
                    logging.warning("Failed to activate %s %s: %s", service_name, char_name, e)
                #NEW CODE: Increase delay for service activation stability
                await asyncio.sleep(0.2)  # NEW CODE (was 0.1)
    
    async def deactivate_service(self, service_name):
        service = self.get_service_by_name(service_name)
        for characteristic in service.characteristics:
            char_name = dean_service_lookup.get(characteristic.uuid, None)
            if char_name is None:
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

    async def model_update_start(self):
        logging.info('%s: Model update start', self.config_dict['address'])
        send_packet = ModelPacket(cmd=MODEL_UPDATE_CMD_START)
        await self.ble_client.write_gatt_char(DEAN_UUID_SOUND_MODEL_CHAR, send_packet.pack())

    async def model_send_worker(self):
        total_chunk = self.model_size // self.model_chunk_size + 1
        if self.model_seq > total_chunk:
            send_packet = ModelPacket(cmd=MODEL_UPDATE_CMD_END)
            await self.ble_client.write_gatt_char(DEAN_UUID_SOUND_MODEL_CHAR, send_packet.pack())
            return
        try:
            with open(self.model_path, 'rb') as f:
                model_data = f.read()
            model_chunk = model_data[self.model_seq * self.model_chunk_size:(self.model_seq + 1) * self.model_chunk_size]
            send_packet = ModelDataPacket(cmd=MODEL_UPDATE_CMD_DATA, seq=self.model_seq, data=model_chunk)
            logging.info('%s: Sending model data %d/%d', self.config_dict['address'], self.model_seq, total_chunk)
            await self.ble_client.write_gatt_char(DEAN_UUID_SOUND_MODEL_CHAR, send_packet.pack())
        except Exception as e:
            logging.warning("Model send error: %s", e)
            self.sending_model = False
    
    async def model_train_start(self):
        logging.info('%s: Model training start', self.config_dict['address'])
        args = ['python3', 'training.py', self.config_dict['address']]
        subprocess.Popen(args)
        
    async def unitspace_existence_simulation(self):
        await asyncio.sleep(0.005)
        try:
            # logging.info("unitspace existence simulation start")
            debug_data = (10, 20, 30, 40)
            format_string = '<BBBB'
            debug_packed_data = struct.pack(format_string, *debug_data)
            await self.ble_client.write_gatt_char(DEAN_UUID_GRIDEYE_PREDICTION_CHAR, debug_packed_data)
            # logging.info("unitspace existence simulation end")
        except Exception as e:
            logging.warning(e)
            return
        
    async def unitspace_existence_estimation(self, command_string):
        await asyncio.sleep(0.005)
        try:
            # logging.info("unitspace existence estimation start")
            byte_string = command_string.encode("utf-8")
            packed_validity_packet = struct.pack(f"{len(byte_string)}s", byte_string)
            
            await self.ble_client.write_gatt_char(DEAN_UUID_GRIDEYE_PREDICTION_CHAR, packed_validity_packet)
            # logging.info("unitspace existence estimation end")
        except Exception as e:
            logging.warning(e)
            return
        
    async def unitspace_existenc_intial_configuration(self, command_string):
        await asyncio.sleep(0.005)
        
    async def _connect_device(self):
        try:
            await self.ble_client.connect()
            #NEW CODE: Wait for services to be discovered (up to ~1 second)
            for _ in range(10):  # Wait up to 1 second in 0.1초 간격
                if self.ble_client.services:
                    break
                await asyncio.sleep(0.1)
            #OLD CODE: await asyncio.sleep(0.1)
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
            logging.warning("Error in _connect_device: %s", e)
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
        retry_count = 3
        for attempt in range(retry_count):
            try:
                return await self._ble_worker()
            except DeviceError as e:
                logging.warning(f"{self.config_dict['address']}: Connection failed, retrying... ({attempt + 1}/{retry_count})")
                await asyncio.sleep(2)  # 2초 후 재시도
        logging.error(f"{self.config_dict['address']}: Failed to connect after {retry_count} attempts")
        return False    
            

class DeviceManager:
    # def __init__(self):

    async def process_command(self, commands):
        cmd = commands[0]
        if len(commands) > 1:
            address = commands[1]
            device_obj = get_device_by_address(address)
            if device_obj is None:
                print("something wrong 1")
                return (address + ' is not registered').encode()
            if device_obj.is_connected == False:
                print("something wrong 2")
                return (address + ' is not connected').encode()

        if cmd == 'config':
            await device_obj.config_device(commands[2], commands[3])
            return_msg = f"address: {device_obj.config_dict['address']}, type: {device_obj.config_dict['type']}, name: {device_obj.config_dict['name']}, location: {device_obj.config_dict['location']}"
            return return_msg.encode()
        
        if cmd == 'reset':
            await device_obj.reset_device()
            return_msg = f"Reset DEAN {commands[1]}"
            return return_msg.encode()

        elif cmd == 'service':
            if commands[2] == 'enable':
                if await device_obj.activate_characteristic(commands[3], commands[4]):
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} enabled".encode()
                else:
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} enable failed".encode()
            elif commands[2] == 'disable':
                if await device_obj.deactivate_characteristic(commands[3], commands[4]):
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} disabled".encode()
                else:
                    return f"{commands[1]}: characteristic {commands[3]} {commands[4]} disable failed".encode()
            else:
                return "Argument 2 must be 'enable' or 'disable'".encode()
        
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
        
        elif cmd == 'update':
            if device_obj.sending_model:
                return "Model update is in progress".encode()
            else:
                await device_obj.model_update_start()
                return "Model update started".encode()
        
        elif cmd == 'feature':
            if commands[2] == 'start':
                send_packet = ModelPacket(cmd=FEATURE_COLLECTION_CMD_START)
                await device_obj.ble_client.write_gatt_char(DEAN_UUID_SOUND_MODEL_CHAR, send_packet.pack())
                return "Feature collection started".encode()
            elif commands[2] == 'stop':
                send_packet = ModelPacket(cmd=FEATURE_COLLECTION_CMD_END)
                await device_obj.ble_client.write_gatt_char(DEAN_UUID_SOUND_MODEL_CHAR, send_packet.pack())
                return "Feature collection ended".encode()
            else:
                return "Argument 2 must be 'start' or 'end'".encode()
        
        elif cmd == 'train':
            await device_obj.model_train_start()
            return "Model training started".encode()
        
        else:
            print("What? " + cmd + " " + str(type(cmd)))
            return b''
        
