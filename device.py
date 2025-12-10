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
from dataclasses import dataclass

from dean_uuid import *
from packet import *
from dean_identity import KnownDeanTable, try_normalize_mac_string
from unitspace_manager import UnitspaceManager
from unitspace_manager_with_timestamp import UnitspaceManager_new_new

connected_devices = {}
known_deans = KnownDeanTable()

def get_device_by_address(address):
    device = connected_devices.get(address, None)
    if device is not None:
        return device
    entry = known_deans.get(address)
    if entry is None:
        return None
    return connected_devices.get(entry.relay_address, None)

class DeviceError(Exception):
    pass

# unitspace_manager = UnitspaceManager()
# unitspace_manager = UnitspaceManager_new()
unitspace_manager = UnitspaceManager_new_new()

@dataclass
class FileTransferState:
    path: str = ''
    size: int = 0
    seq: int = 0
    sending: bool = False


@dataclass
class ModelTransferState:
    path: str = ''
    size: int = 0
    seq: int = 0
    sending: bool = False


def _canonical_mac(mac: str) -> str:
    normalized = try_normalize_mac_string(mac)
    if normalized is None:
        raise DeviceError(f"Invalid MAC address {mac}")
    return normalized


def _mac_slug(mac: str) -> str:
    return _canonical_mac(mac).replace(':', '')

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
        'config': ['file'],
        'sound': ['model'],
        'grideye': ['prediction'],
        'inference': ['rawdata', 'predict', 'debugstr']
    }

    file_chunk_size = 128
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
        self.training_targets = set()
        self.dataset_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "programdata", "datasets", dev.address)
        os.makedirs(self.dataset_path, exist_ok=True)
        self.model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "programdata", "models", dev.address + ".tflite")
        self.model_transfers = {}
        self.file_transfers = {}
        self.collecting_feature = set()

        self.user_in = False
        
        self.enable = Device.service_enable_default
    
    def __repr__(self):
        return f"{self.__class__.__name__}: {self.config_dict['address']}, {self.config_dict['type']}, {self.config_dict['name']}, {self.config_dict['location']}"

    def _config_dir(self):
        config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "config")
        os.makedirs(config_path, exist_ok=True)
        return config_path

    def _config_path(self, dean_mac: str):
        slug = _mac_slug(dean_mac)
        return os.path.join(self._config_dir(), f"{slug}.json")

    def _model_path_for(self, dean_mac: str):
        model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "programdata", "models")
        os.makedirs(model_dir, exist_ok=True)
        return os.path.join(model_dir, f"{_mac_slug(dean_mac)}.tflite")

    @staticmethod
    def _payload_to_bytes(payload) -> bytes:
        if isinstance(payload, bytes):
            return payload
        if isinstance(payload, bytearray):
            return bytes(payload)
        if isinstance(payload, str):
            return payload.encode('utf-8')
        if isinstance(payload, bool):
            return b'\x01' if payload else b'\x00'
        if isinstance(payload, int):
            return bytes([payload])
        raise DeviceError(f"Unsupported payload type {type(payload)}")

    def _write_with_target(self, char_uuid, target_mac: str, payload):
        canonical_mac = _canonical_mac(target_mac)
        payload_bytes = self._payload_to_bytes(payload)
        prefixed_payload = known_deans.build_downstream(canonical_mac, payload_bytes)
        return self.ble_client.write_gatt_char(char_uuid, prefixed_payload)

    def _ensure_identity(self, dean_mac: str):
        return known_deans.ensure(dean_mac, relay_address=self.config_dict['address'], device_type=self.config_dict['type'])

    def _get_file_state(self, dean_mac: str) -> FileTransferState:
        canonical = _canonical_mac(dean_mac)
        return self.file_transfers.setdefault(canonical, FileTransferState())

    def _get_model_state(self, dean_mac: str) -> ModelTransferState:
        canonical = _canonical_mac(dean_mac)
        return self.model_transfers.setdefault(canonical, ModelTransferState())

    def is_file_transfer_active(self, dean_mac: str) -> bool:
        canonical = try_normalize_mac_string(dean_mac)
        if canonical is None:
            return False
        state = self.file_transfers.get(canonical)
        return state.sending if state else False

    def is_model_transfer_active(self, dean_mac: str) -> bool:
        canonical = try_normalize_mac_string(dean_mac)
        if canonical is None:
            return False
        state = self.model_transfers.get(canonical)
        return state.sending if state else False

    def is_training(self, dean_mac: str) -> bool:
        canonical = try_normalize_mac_string(dean_mac)
        if canonical is None:
            return False
        return canonical in self.training_targets
    
    async def remove(self):
        try:
            if self.ble_client is not None:
                await self.ble_client.disconnect()
        except Exception as e:
            logging.warning("Error during disconnect: %s", e)
        try:
            address = self.config_dict.get("address")
            if address in connected_devices:
                connected_devices.pop(address, None)
            known_deans.mark_disconnected(address)
        except Exception as e:
            logging.warning("Error during device removal: %s", e)
        finally:
            del self
        
    def check_room_status(self, data):
        value = struct.unpack('B', data[0:1])[0]
    
    def _ble_notify_callback(self, sender, data):
        service_name = dean_service_lookup[sender.service_uuid]
        char_name = dean_service_lookup[sender.uuid]
        received_time = time.time()

        try:
            dean_entry, payload = known_deans.parse_upstream(
                data,
                self.config_dict['address'],
                self.config_dict['type'],
                self.config_dict['location']
            )
        except ValueError:
            logging.warning("Received %s/%s packet without MAC prefix", service_name, char_name)
            return

        dean_mac = dean_entry.mac
        location = dean_entry.location or self.config_dict['location']
        device_type = dean_entry.device_type or self.config_dict['type']

        if service_name == 'config':
            if char_name == 'file':
                recv_packet = FilePacket.unpack(payload)
                state = self._get_file_state(dean_mac)
                if recv_packet.cmd == FILE_TRANSFER_CMD_START:
                    if not state.sending:
                        state.sending = True
                        state.seq = 0
                        asyncio.create_task(self.file_send_worker(dean_mac))
                elif recv_packet.cmd == FILE_TRANSFER_CMD_DATA:
                    recv_packet = FileAckPacket.unpack(payload)
                    state.seq = recv_packet.seq + 1
                    asyncio.create_task(self.file_send_worker(dean_mac))
                elif recv_packet.cmd == FILE_TRANSFER_CMD_END:
                    logging.info('%s: File transfer completed', dean_mac)
                    state.sending = False
                    state.seq = 0
                elif recv_packet.cmd == FILE_TRANSFER_CMD_FAIL:
                    logging.info('%s: File transfer failed', dean_mac)
                    state.sending = False
                    state.seq = 0
                elif recv_packet.cmd == FILE_TRANSFER_CMD_REMOVE:
                    logging.info('%s: File removed', dean_mac)
        
        elif service_name == 'sound':
            if char_name == 'model':
                recv_packet = ModelPacket.unpack(payload)
                state = self._get_model_state(dean_mac)
                if recv_packet.cmd == MODEL_UPDATE_CMD_START:
                    if not state.sending:
                        state.sending = True
                        state.seq = 0
                        asyncio.create_task(self.model_send_worker(dean_mac))
                elif recv_packet.cmd == MODEL_UPDATE_CMD_DATA:
                    recv_packet = ModelAckPacket.unpack(payload)
                    state.seq = recv_packet.seq + 1
                    asyncio.create_task(self.model_send_worker(dean_mac))
                elif recv_packet.cmd == MODEL_UPDATE_CMD_END:
                    logging.info('%s: Model update completed', dean_mac)
                    state.sending = False
                    state.seq = 0
                elif recv_packet.cmd == MODEL_UPDATE_CMD_FAIL:
                    logging.info('%s: Model update failed', dean_mac)
                    state.sending = False
                    state.seq = 0
                elif recv_packet.cmd == MODEL_UPDATE_CMD_REMOVE:
                    logging.info('%s: Model removed', dean_mac)

                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_START:
                    self.collecting_feature.add(dean_mac)
                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_DATA:
                    if not self.sound_queue.full():
                        self.sound_queue.put([location, device_type,
                                               dean_mac, service_name, char_name,
                                               received_time, payload])
                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_FINISH:
                    if not self.sound_queue.full():
                        self.sound_queue.put([location, device_type,
                                               dean_mac, service_name, char_name,
                                               received_time, payload])
                elif recv_packet.cmd == FEATURE_COLLECTION_CMD_END:
                    self.collecting_feature.discard(dean_mac)

        elif service_name == 'inference':
            if char_name == 'rawdata':
                fmt = '<BBBfffffB20b'
                unpacked_data = struct.unpack(fmt, payload)
                unpacked_data_list = list(unpacked_data)
                if unpacked_data_list[0] == 1:
                    # Unitspace management start
                    asyncio.create_task(unitspace_manager.unitspace_existence_estimation(location, device_type,
                                                dean_mac, service_name, char_name,
                                                received_time, unpacked_data_list, payload))
                else:
                    self.check_room_status(payload)
                    if not self.data_queue.full():
                        self.data_queue.put([location, device_type,
                                            dean_mac, service_name, char_name,
                                            received_time, payload])
                    # if not self.unitspace_queue.full():
                
            elif char_name == 'predict':
                print("WIP : mqtt service required for handling inference result")   
            elif char_name == 'debugstr':
                if not self.data_queue.full():
                    self.data_queue.put([location, device_type,
                                         dean_mac, service_name, char_name,
                                         received_time, payload])
                if not self.log_queue.full():
                    self.log_queue.put([location, device_type,
                                         dean_mac, service_name, char_name,
                                         received_time, payload])
        
    def _ble_disconnected_callback(self, client):
        logging.info('%s: %s disconnected', client.address, self.config_dict['type'])
        self.is_connected = False
        for state in self.model_transfers.values():
            state.sending = False
            state.seq = 0
        for state in self.file_transfers.values():
            state.sending = False
            state.seq = 0
        known_deans.mark_disconnected(self.config_dict['address'])
    
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

    async def config_device(self, dean_mac, target, data):
        entry = self._ensure_identity(dean_mac)
        if target == 'name':
            entry.name = data
        elif target == 'location':
            entry.location = data
        elif target in self.config_dict:
            self.config_dict[target] = data
        else:
            return
        char_uuid = dean_service_dict['config'][target]
        self.save_dean_config(entry)
        await self._write_with_target(char_uuid, entry.mac, data)

    async def load_config(self, dean_mac=None):
        if dean_mac is None:
            config_path = self._config_dir()
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
            return False

        entry = self._ensure_identity(dean_mac)
        file_path = self._config_path(entry.mac)
        if os.path.isfile(file_path):
            with open(file_path) as f:
                json_data = json.load(f)
                entry.name = json_data.get('name', entry.name)
                entry.location = json_data.get('location', entry.location)
            try:
                await self._write_with_target(DEAN_UUID_CONFIG_NAME_CHAR, entry.mac, entry.name or '')
                await self._write_with_target(DEAN_UUID_CONFIG_LOCATION_CHAR, entry.mac, entry.location or '')
                return True
            except Exception as e:
                logging.warning(e)
                return False
        return False
    
    def save_config(self):
        config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "config")
        os.makedirs(config_path, exist_ok=True)
        file_path = os.path.join(config_path, self.config_dict['address'] + '.json')
        with open(file_path, 'w') as save:
            json.dump(self.config_dict, save, indent=4)

    def save_dean_config(self, entry):
        payload = {
            'address': entry.mac,
            'type': entry.device_type,
            'name': entry.name,
            'location': entry.location,
        }
        with open(self._config_path(entry.mac), 'w') as save:
            json.dump(payload, save, indent=4)

    async def reset_device(self, dean_mac):
        char_uuid = dean_service_dict['base']['reset']
        await self._write_with_target(char_uuid, dean_mac, True)
            
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
            return True
        return False
    
    async def deactivate_service(self, service_name):
        # service = self.get_service_by_name(service_name)
        # for characteristic in service.characteristics:
        #     char_name = dean_service_lookup.get(characteristic.uuid, None)
        #     if char_name is None:
        #         continue
        #     try:
        #         await self.ble_client.stop_notify(characteristic.uuid)
        #     except Exception as e:
        #         logging.warning(e)
        #         pass
        enable_list = self.enable.get(service_name, None)
        if enable_list is not None:
            for char_name in enable_list:
                try:
                    await self.deactivate_characteristic(service_name, char_name)
                except Exception as e:
                    logging.warning("Failed to deactivate %s %s: %s", service_name, char_name, e)
                #NEW CODE: Increase delay for service activation stability
                await asyncio.sleep(0.2)  # NEW CODE (was 0.1)
            return True
        return False

    async def init_services(self):
        try:
            for service in self.ble_client.services:
                # if service.uuid == DEAN_UUID_CONFIG_SERVICE:
                #     continue
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

    async def file_transfer_start(self, dean_mac, file_path, target_path):
        state = self._get_file_state(dean_mac)
        state.path = file_path
        with open(file_path, 'rb') as f:
            file_data = f.read()
        state.size = len(file_data)
        state.seq = 0
        state.sending = True
        logging.info('%s: File transfer start to %s', dean_mac, target_path)
        send_packet = FileDataPacket(cmd=FILE_TRANSFER_CMD_START, seq=0, size=len(target_path), data=bytearray(target_path, 'utf-8'))
        await self._write_with_target(DEAN_UUID_CONFIG_FILE_TRANSFER_CHAR, dean_mac, send_packet.pack())

    async def file_send_worker(self, dean_mac):
        state = self._get_file_state(dean_mac)
        if not state.sending:
            return
        total_chunk = state.size // self.file_chunk_size + 1
        if state.seq > total_chunk:
            send_packet = FilePacket(cmd=FILE_TRANSFER_CMD_END)
            for _ in range(3):
                await self._write_with_target(DEAN_UUID_CONFIG_FILE_TRANSFER_CHAR, dean_mac, send_packet.pack())
                await asyncio.sleep(1)
                if not state.sending:
                    break
            return
        try:
            with open(state.path, 'rb') as f:
                file_data = f.read()
            start_idx = state.seq * self.file_chunk_size
            end_idx = (state.seq + 1) * self.file_chunk_size
            file_chunk = file_data[start_idx:end_idx]
            send_packet = FileDataPacket(cmd=FILE_TRANSFER_CMD_DATA, seq=state.seq, size=len(file_chunk), data=file_chunk)
            if state.seq % 1 == 0 or state.seq == total_chunk:
                logging.info('%s: Sending file data %d/%d', dean_mac, state.seq, total_chunk)
            await self._write_with_target(DEAN_UUID_CONFIG_FILE_TRANSFER_CHAR, dean_mac, send_packet.pack())
        except Exception as e:
            logging.warning("File send error (%s): %s", dean_mac, e)
            state.sending = False

    async def file_remove(self, dean_mac, target_path):
        logging.info('%s: Remove %s', dean_mac, target_path)
        send_packet = FileDataPacket(cmd=FILE_TRANSFER_CMD_REMOVE, seq=0, size=len(target_path), data=bytearray(target_path, 'utf-8'))
        await self._write_with_target(DEAN_UUID_CONFIG_FILE_TRANSFER_CHAR, dean_mac, send_packet.pack())

    async def model_update_start(self, dean_mac):
        state = self._get_model_state(dean_mac)
        model_path = self._model_path_for(dean_mac)
        if not os.path.isfile(model_path):
            logging.warning('%s: Model file %s not found', dean_mac, model_path)
            return False
        with open(model_path, 'rb') as f:
            model_data = f.read()
        state.size = len(model_data)
        state.path = model_path
        state.seq = 0
        state.sending = True
        logging.info('%s: Model update start', dean_mac)
        send_packet = ModelPacket(cmd=MODEL_UPDATE_CMD_START)
        await self._write_with_target(DEAN_UUID_SOUND_MODEL_CHAR, dean_mac, send_packet.pack())
        return True

    async def send_sound_packet(self, dean_mac, packet):
        await self._write_with_target(DEAN_UUID_SOUND_MODEL_CHAR, dean_mac, packet.pack())

    async def model_send_worker(self, dean_mac):
        state = self._get_model_state(dean_mac)
        if not state.sending:
            return
        total_chunk = state.size // self.model_chunk_size + 1
        if state.seq > total_chunk:
            send_packet = ModelPacket(cmd=MODEL_UPDATE_CMD_END)
            for _ in range(3):
                await self._write_with_target(DEAN_UUID_SOUND_MODEL_CHAR, dean_mac, send_packet.pack())
                await asyncio.sleep(1)
                if not state.sending:
                    break
            return
        try:
            with open(state.path, 'rb') as f:
                model_data = f.read()
            start_idx = state.seq * self.model_chunk_size
            end_idx = (state.seq + 1) * self.model_chunk_size
            model_chunk = model_data[start_idx:end_idx]
            send_packet = ModelDataPacket(cmd=MODEL_UPDATE_CMD_DATA, seq=state.seq, data=model_chunk)
            if state.seq % 10 == 0 or state.seq == total_chunk:
                logging.info('%s: Sending model data %d/%d', dean_mac, state.seq, total_chunk)
            await self._write_with_target(DEAN_UUID_SOUND_MODEL_CHAR, dean_mac, send_packet.pack())
        except Exception as e:
            logging.warning("Model send error (%s): %s", dean_mac, e)
            state.sending = False
    
    async def model_remove(self, dean_mac):
        logging.info('%s: Remove model', dean_mac)
        send_packet = ModelPacket(cmd=MODEL_UPDATE_CMD_REMOVE)
        await self._write_with_target(DEAN_UUID_SOUND_MODEL_CHAR, dean_mac, send_packet.pack())
    
    async def model_train_start(self, dean_mac):
        canonical = _canonical_mac(dean_mac)
        if canonical in self.training_targets:
            return
        logging.info('%s: Model training start', canonical)
        self.training_targets.add(canonical)
        training_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'training.py')
        args = ['python3', training_script, canonical]
        proc = await asyncio.create_subprocess_exec(*args)
        async def monitor():
            await proc.wait()
            logging.info(f"{canonical}: Training done")
            self.training_targets.discard(canonical)
        asyncio.create_task(monitor())
    
    async def unitspace_existence_simulation(self, dean_mac):
        await asyncio.sleep(0.005)
        try:
            # logging.info("unitspace existence simulation start")
            debug_data = (10, 20, 30, 40)
            format_string = '<BBBB'
            debug_packed_data = struct.pack(format_string, *debug_data)
            await self._write_with_target(DEAN_UUID_GRIDEYE_PREDICTION_CHAR, dean_mac, debug_packed_data)
            # logging.info("unitspace existence simulation end")
        except Exception as e:
            logging.warning(e)
            return
        
    async def unitspace_existence_callback(self, dean_mac, command_string):
        await asyncio.sleep(0.005)
        try:
            # logging.info("unitspace existence estimation start")
            byte_string = command_string.encode("utf-8")
            packed_validity_packet = struct.pack(f"{len(byte_string)}s", byte_string)
            
            await self._write_with_target(DEAN_UUID_GRIDEYE_PREDICTION_CHAR, dean_mac, packed_validity_packet)
            # logging.info("unitspace existence estimation end")
        except Exception as e:
            logging.warning(e)
            return
        
    async def unitspace_existenc_intial_configuration(self, dean_mac, command_string):
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

    def _resolve_connection(self, address):
        device_obj = get_device_by_address(address)
        if device_obj is None:
            return None, f"{address} is not registered"
        if not device_obj.is_connected:
            return None, f"{address} is not connected"
        return device_obj, None

    def _resolve_dean_target(self, identifier):
        entry = known_deans.get(identifier)
        if entry is None:
            return None, None, f"{identifier} is not registered"
        device_obj = get_device_by_address(entry.mac)
        if device_obj is None or not device_obj.is_connected:
            return None, entry, f"{identifier} is not connected"
        return device_obj, entry, None

    async def process_command(self, commands):
        cmd = commands[0]
        device_obj = None
        dean_entry = None
        if cmd in {'config', 'reset', 'model', 'feature', 'file'}:
            if len(commands) < 2:
                return "Target MAC is required".encode()
            device_obj, dean_entry, error = self._resolve_dean_target(commands[1])
            if error:
                return error.encode()
        elif cmd in {'service'} and len(commands) > 1:
            device_obj, error = self._resolve_connection(commands[1])
            if error:
                return error.encode()
        elif cmd not in {'list', 'apply'} and len(commands) > 1:
            device_obj, error = self._resolve_connection(commands[1])
            if error:
                return error.encode()

        if cmd == 'config':
            await device_obj.config_device(dean_entry.mac, commands[2], commands[3])
            return f"{dean_entry.mac}: {commands[2]} updated".encode()
        
        if cmd == 'reset':
            await device_obj.reset_device(dean_entry.mac)
            return f"Reset DEAN {dean_entry.mac}".encode()

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
            elif commands[2] == 'activate':
                if await device_obj.activate_service(commands[3]):
                    return f"{commands[1]}: service {commands[3]} activated".encode()
                else:
                    return f"{commands[1]}: service {commands[3]} activate failed".encode()
            elif commands[2] == 'deactivate':
                if await device_obj.deactivate_service(commands[3]):
                    return f"{commands[1]}: service {commands[3]} deactivated".encode()
                else:
                    return f"{commands[1]}: service {commands[3]} deactivate failed".encode()
            else:
                return "Argument 2 must be 'enable', 'disable', 'activate all', 'deactivate all'".encode()
        elif cmd == 'list':
            entries = list(known_deans.iter_entries())
            if entries:
                return_msg = f"{'Dean MAC':<20}{'Relay':<20}{'Type':<10}{'Location':<15}{'Connected':<10}\n"
                for entry in entries:
                    return_msg += f"{entry.mac:<20}{entry.relay_address:<20}{entry.device_type:<10}{entry.location:<15}{entry.connected:<10}\n"
            else:
                return_msg = f"{'Address':<20}{'Type':<10}{'Name':<15}{'Location':<15}{'Connected':<10}\n"
                for value in connected_devices.values():
                    return_msg += f"{value.config_dict['address']:<20}{value.config_dict['type']:<10}{value.config_dict['name']:<15}{value.config_dict['location']:<15}{value.is_connected:<10}\n"
            return return_msg.encode()

        elif cmd == 'apply':
            entries = list(known_deans.iter_entries())
            if not entries:
                return "No known DEAN nodes".encode()
            for entry in entries:
                device = get_device_by_address(entry.mac)
                if device and device.is_connected:
                    await device.load_config(entry.mac)
                    await asyncio.sleep(0.1)
            return "Config data applied".encode()
        
        elif cmd == 'model':
            if commands[2] == 'update':
                if device_obj.is_model_transfer_active(dean_entry.mac):
                    return f"{dean_entry.mac} Model update is in progress".encode()
                started = await device_obj.model_update_start(dean_entry.mac)
                if started:
                    return f"{dean_entry.mac} Model update started".encode()
                return f"{dean_entry.mac} Model file not found".encode()
            elif commands[2] == 'train':
                if device_obj.is_training(dean_entry.mac):
                    return f"{dean_entry.mac} Model training is in progress".encode()
                await device_obj.model_train_start(dean_entry.mac)
                return f"{dean_entry.mac} Model train started".encode()
            elif commands[2] == 'remove':
                await device_obj.model_remove(dean_entry.mac)
                return f"{dean_entry.mac} Model removed".encode()
            else:
                return "Argument 2 must be 'update', 'train' or 'remove'".encode()

        elif cmd == 'feature':
            if commands[2] == 'start':
                await device_obj.send_sound_packet(dean_entry.mac, ModelPacket(cmd=FEATURE_COLLECTION_CMD_START))
                return f"{dean_entry.mac} feature collection started".encode()
            elif commands[2] == 'stop':
                await device_obj.send_sound_packet(dean_entry.mac, ModelPacket(cmd=FEATURE_COLLECTION_CMD_END))
                return f"{dean_entry.mac} feature collection ended".encode()
            else:
                return "Argument 2 must be 'start' or 'end'".encode()     

        elif cmd == 'file':
            file_path = commands[2]
            target_path = commands[3]
            if not os.path.isfile(file_path):
                return f"File {file_path} does not exist".encode()
            if device_obj.is_file_transfer_active(dean_entry.mac):
                return f"{dean_entry.mac} File transfer is in progress".encode()
            await device_obj.file_transfer_start(dean_entry.mac, file_path, target_path)
            return f"{dean_entry.mac} File transfer started for {file_path} to {target_path}".encode()   
        else:
            print("What? " + cmd + " " + str(type(cmd)))
            return b''
