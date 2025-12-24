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

DEAN_STATUS_TIMEOUT_SECONDS = 120

def get_device_by_address(address):
    device = connected_devices.get(address, None)
    if device is not None:
        return device
    entry = known_deans.get(address)
    if entry is None:
        return None
    return connected_devices.get(entry.relay_address, None)


def load_known_deans_from_disk():
    config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "config")
    if not os.path.isdir(config_path):
        return 0
    loaded = 0
    for filename in os.listdir(config_path):
        if not filename.endswith(".json"):
            continue
        file_path = os.path.join(config_path, filename)
        try:
            with open(file_path) as f:
                json_data = json.load(f)
        except Exception:
            continue
        dean_mac = json_data.get("address")
        canonical = try_normalize_mac_string(dean_mac)
        if canonical is None:
            continue
        if json_data.get("type") in {"DE&N_RELAY", "slimhub"}:
            continue

        # Migrate legacy slug filenames (AABBCCDDEEFF.json) to colon filenames (AA:BB:CC:DD:EE:FF.json).
        colon_path = os.path.join(config_path, f"{canonical}.json")
        if file_path != colon_path and not os.path.exists(colon_path):
            try:
                with open(colon_path, "w") as f:
                    json.dump(json_data, f, indent=4)
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            except Exception:
                pass

        entry = known_deans.ensure(canonical, device_type=json_data.get("type", ""))
        entry.name = json_data.get("name", entry.name)
        entry.location = json_data.get("location", entry.location)
        loaded += 1
    return loaded


class ConnectionStatusManager:
    def __init__(self, dean_table: KnownDeanTable, timeout_seconds: float = DEAN_STATUS_TIMEOUT_SECONDS, refresh_interval_seconds: float = 5.0):
        self._dean_table = dean_table
        self._timeout_seconds = float(timeout_seconds)
        self._refresh_interval_seconds = float(refresh_interval_seconds)

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def run(self, stop_event: asyncio.Event):
        while not stop_event.is_set():
            try:
                self._dean_table.refresh_connection_states(self._timeout_seconds)
            except Exception as e:
                logging.warning("ConnectionStatusManager refresh failed: %s", e)
            await asyncio.sleep(self._refresh_interval_seconds)


connection_status_manager = ConnectionStatusManager(known_deans)

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
    gatt_min_gap_seconds = 0.03
    config_write_gap_seconds = 0.50
    heartbeat_config_reapply_cooldown_seconds = 60.0

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

        # Heartbeat-driven config reapply (name/location) for downstream DEAN nodes.
        self._config_applied = set()
        self._config_apply_inflight = set()
        self._config_apply_last_attempt = {}

        # Serialize GATT ops to avoid BlueZ "Unlikely Error" from overlapping operations.
        self._gatt_lock = asyncio.Lock()
        self._next_gatt_ok_at = 0.0
    
    def __repr__(self):
        return f"{self.__class__.__name__}: {self.config_dict['address']}, {self.config_dict['type']}, {self.config_dict['name']}, {self.config_dict['location']}"

    def _config_dir(self):
        config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "config")
        os.makedirs(config_path, exist_ok=True)
        return config_path

    def _config_path(self, dean_mac: str):
        canonical = _canonical_mac(dean_mac)
        return os.path.join(self._config_dir(), f"{canonical}.json")

    def _config_paths(self, dean_mac: str):
        canonical = _canonical_mac(dean_mac)
        human = os.path.join(self._config_dir(), f"{canonical}.json")
        slug = os.path.join(self._config_dir(), f"{_mac_slug(canonical)}.json")
        return human, slug

    def _read_dean_config_file(self, dean_mac: str):
        for path in self._config_paths(dean_mac):
            if os.path.isfile(path):
                try:
                    with open(path) as f:
                        return json.load(f)
                except Exception:
                    return None
        return None

    def _write_dean_config_file(self, dean_mac: str, payload: dict):
        human, slug = self._config_paths(dean_mac)
        with open(human, 'w') as save:
            json.dump(payload, save, indent=4)
        # Backward-compat read supports legacy slug filenames, but we only write the
        # colon-form filename going forward to keep config directory human-readable.

    def _hydrate_dean_entry_from_disk(self, entry) -> bool:
        json_data = self._read_dean_config_file(entry.mac)
        if not json_data:
            return False
        entry.name = entry.name or json_data.get("name", "")
        entry.location = entry.location or json_data.get("location", "")
        entry.device_type = entry.device_type or json_data.get("type", "")
        return True

    def _is_heartbeat_rawdata_packet(self, payload: bytes) -> bool:
        num_sound_labels = len(self.sound_classlist)
        expected_len = 24 + num_sound_labels
        if len(payload) < expected_len:
            return False
        fmt = '<BBBfffff' + 'B' + str(num_sound_labels) + 'b'
        try:
            unpacked = struct.unpack(fmt, payload[:expected_len])
        except struct.error:
            return False
        grideye, direction, _env = unpacked[:3]
        temp, humid, iaq, eco2, bvoc = unpacked[3:8]
        sound_flag = unpacked[8]
        sound_logits = unpacked[9:]
        if grideye != 0 or direction != 0 or sound_flag != 0:
            return False
        if any(abs(v) > 1e-6 for v in (temp, humid, iaq, eco2, bvoc)):
            return False
        return all(v == -128 for v in sound_logits)

    def _maybe_apply_dean_config_on_heartbeat(self, dean_entry, payload: bytes):
        if not self._is_heartbeat_rawdata_packet(payload):
            return
        canonical = try_normalize_mac_string(dean_entry.mac)
        if canonical is None:
            return
        if canonical in self._config_apply_inflight:
            return
        last = self._config_apply_last_attempt.get(canonical, 0.0)
        now = time.time()
        if now - last < self.heartbeat_config_reapply_cooldown_seconds:
            return
        json_data = self._read_dean_config_file(canonical) or {}

        dean_entry.name = json_data.get("name", dean_entry.name)
        dean_entry.location = json_data.get("location", dean_entry.location)
        dean_entry.device_type = json_data.get("type", dean_entry.device_type)
        if not dean_entry.location:
            dean_entry.location = self.config_dict.get("location", "")

        payload_to_save = {
            "address": dean_entry.mac,
            "type": dean_entry.device_type,
            "name": dean_entry.name,
            "location": dean_entry.location,
        }
        if any(json_data.get(k) != payload_to_save.get(k) for k in payload_to_save):
            try:
                self._write_dean_config_file(dean_entry.mac, payload_to_save)
            except Exception as e:
                logging.warning("Failed to persist downstream config for %s: %s", dean_entry.mac, e)

        self._config_apply_last_attempt[canonical] = now
        self._config_apply_inflight.add(canonical)

        async def _apply():
            try:
                ok = await self.load_config(canonical)
                if ok:
                    self._config_applied.add(canonical)
                    logging.info("%s: downstream config reapplied on heartbeat", canonical)
            except Exception as e:
                logging.warning("Config apply failed for %s: %s", canonical, e)
            finally:
                self._config_apply_inflight.discard(canonical)

        asyncio.create_task(_apply())

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

    async def _gatt_run(self, op_label: str, op_coro_factory, *, post_gap_seconds: float = 0.0):
        async with self._gatt_lock:
            now = time.monotonic()
            if now < self._next_gatt_ok_at:
                await asyncio.sleep(self._next_gatt_ok_at - now)
            try:
                return await op_coro_factory()
            except Exception as e:
                raise DeviceError(f"GATT {op_label} failed: {e}") from e
            finally:
                self._next_gatt_ok_at = time.monotonic() + self.gatt_min_gap_seconds + float(post_gap_seconds)

    async def _gatt_write(self, char_uuid, payload: bytes, *, response: bool = False, post_gap_seconds: float = 0.0, label: str = "write"):
        async def _op():
            return await self.ble_client.write_gatt_char(char_uuid, payload, response=response)

        return await self._gatt_run(label, _op, post_gap_seconds=post_gap_seconds)

    async def _gatt_read(self, char_uuid, *, label: str = "read"):
        async def _op():
            return await self.ble_client.read_gatt_char(char_uuid)

        return await self._gatt_run(label, _op)

    async def _gatt_start_notify(self, char_uuid, callback, *, label: str = "start_notify"):
        async def _op():
            return await self.ble_client.start_notify(char_uuid, callback)

        return await self._gatt_run(label, _op)

    async def _gatt_stop_notify(self, char_uuid, *, label: str = "stop_notify"):
        async def _op():
            return await self.ble_client.stop_notify(char_uuid)

        return await self._gatt_run(label, _op)

    async def _write_with_target(self, char_uuid, target_mac: str, payload):
        canonical_mac = _canonical_mac(target_mac)
        payload_bytes = self._payload_to_bytes(payload)
        prefixed_payload = known_deans.build_downstream(canonical_mac, payload_bytes)
        post_gap = self.config_write_gap_seconds if char_uuid in {DEAN_UUID_CONFIG_NAME_CHAR, DEAN_UUID_CONFIG_LOCATION_CHAR} else 0.0
        return await self._gatt_write(char_uuid, prefixed_payload, post_gap_seconds=post_gap, label=f"write_target({canonical_mac})")

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

        # Only these characteristics are expected to be MAC-prefixed multiplexed payloads.
        if not (
            (service_name == 'config' and char_name == 'file') or
            (service_name == 'sound' and char_name == 'model') or
            (service_name == 'inference' and char_name in {'rawdata', 'debugstr', 'predict'})
        ):
            return

        try:
            dean_entry, payload = known_deans.parse_upstream(
                data,
                self.config_dict['address'],
                "DE&N",
                self.config_dict['location']
            )
        except ValueError:
            logging.warning("Received %s/%s packet without MAC prefix", service_name, char_name)
            return

        self._hydrate_dean_entry_from_disk(dean_entry)

        dean_mac = dean_entry.mac
        dean_entry.last_seen = received_time
        dean_entry.last_packet = f"{service_name}/{char_name}"
        dean_entry.last_packet_is_heartbeat = False
        if service_name == 'inference' and char_name == 'rawdata':
            dean_entry.last_packet_is_heartbeat = self._is_heartbeat_rawdata_packet(payload)
            self._maybe_apply_dean_config_on_heartbeat(dean_entry, payload)

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
        self._hydrate_dean_entry_from_disk(entry)
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
        self._config_applied.add(entry.mac)

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
                    await self._gatt_write(
                        DEAN_UUID_CONFIG_NAME_CHAR,
                        bytearray(self.config_dict['name'], 'utf-8'),
                        post_gap_seconds=self.config_write_gap_seconds,
                        label="write_config_name",
                    )
                    await self._gatt_write(
                        DEAN_UUID_CONFIG_LOCATION_CHAR,
                        bytearray(self.config_dict['location'], 'utf-8'),
                        post_gap_seconds=self.config_write_gap_seconds,
                        label="write_config_location",
                    )
                    return True
                except Exception as e:
                    logging.warning("%s: load_config(self) failed: %s", self.config_dict.get("address"), e)
                    return False
            return False

        entry = self._ensure_identity(dean_mac)
        json_data = self._read_dean_config_file(entry.mac)
        if json_data:
            entry.name = json_data.get('name', entry.name)
            entry.location = json_data.get('location', entry.location)
            try:
                await self._write_with_target(DEAN_UUID_CONFIG_NAME_CHAR, entry.mac, entry.name or '')
                await self._write_with_target(DEAN_UUID_CONFIG_LOCATION_CHAR, entry.mac, entry.location or '')
                self._config_applied.add(entry.mac)
                return True
            except Exception as e:
                logging.warning("%s: load_config(%s) failed: %s", self.config_dict.get("address"), entry.mac, e)
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
        self._write_dean_config_file(entry.mac, payload)

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
                    await self._gatt_start_notify(char_uuid, self._ble_notify_callback, label=f"start_notify({service_name}/{char_name})")
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
                    await self._gatt_stop_notify(char_uuid, label=f"stop_notify({service_name}/{char_name})")
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
            logging.warning("%s: init_services failed: %s", self.config_dict.get("address"), e)
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
        await self._gatt_write(
            DEAN_UUID_CTS_CURRENT_TIME_CHAR,
            packed_data,
            post_gap_seconds=self.config_write_gap_seconds,
            label="write_current_time",
        )

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
            await self._write_with_target(DEAN_UUID_INFERENCE_RAWDATA_CHAR, dean_mac, debug_packed_data)
            # logging.info("unitspace existence simulation end")
        except Exception as e:
            logging.warning("%s: unitspace_existence_simulation(%s) failed: %s", self.config_dict.get("address"), dean_mac, e)
            return
        
    async def unitspace_existence_callback(self, dean_mac, command_string):
        await asyncio.sleep(0.005)
        try:
            # logging.info("unitspace existence estimation start")
            byte_string = command_string.encode("utf-8")
            packed_validity_packet = struct.pack(f"{len(byte_string)}s", byte_string)
            
            await self._write_with_target(DEAN_UUID_INFERENCE_RAWDATA_CHAR, dean_mac, packed_validity_packet)
            # logging.info("unitspace existence estimation end")
        except Exception as e:
            logging.warning("%s: unitspace_existence_callback(%s) failed: %s", self.config_dict.get("address"), dean_mac, e)
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
                    self.config_dict['name'] = str(await self._gatt_read(DEAN_UUID_CONFIG_NAME_CHAR, label="read_config_name"), 'utf-8')
                    self.config_dict['location'] = str(await self._gatt_read(DEAN_UUID_CONFIG_LOCATION_CHAR, label="read_config_location"), 'utf-8')
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
            logging.warning("%s: BLE worker failed: %s", self.config_dict.get("address"), e)
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
        if not entry.connected:
            return None, entry, f"{identifier} is not connected"
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
            now = time.time()
            known_deans.refresh_connection_states(DEAN_STATUS_TIMEOUT_SECONDS)
            entries = [
                e for e in known_deans.iter_entries()
                if e.connected or getattr(e, "reconnects", 0) >= 1
            ]
            if entries:
                return_msg = (
                    f"{'Dean MAC':<20}{'Relay':<20}{'Type':<10}{'Name':<15}{'Location':<15}"
                    f"{'Connected':<10}{'LastSeen(s)':<12}{'LastPkt':<18}\n"
                )
                for entry in entries:
                    if entry.last_seen:
                        last_seen_age = str(int(now - entry.last_seen))
                    else:
                        last_seen_age = "-"
                    last_pkt = "heartbeat" if entry.last_packet_is_heartbeat else (entry.last_packet or "-")
                    return_msg += (
                        f"{entry.mac:<20}{entry.relay_address:<20}{entry.device_type:<10}{entry.name:<15}{entry.location:<15}"
                        f"{str(entry.connected):<10}{last_seen_age:<12}{last_pkt:<18}\n"
                    )

                if connected_devices:
                    return_msg += "\n"
                    return_msg += f"{'Relay MAC':<20}{'Type':<12}{'Name':<15}{'Location':<15}{'Connected':<10}\n"
                    for value in connected_devices.values():
                        return_msg += (
                            f"{value.config_dict['address']:<20}{value.config_dict['type']:<12}{value.config_dict['name']:<15}"
                            f"{value.config_dict['location']:<15}{str(value.is_connected):<10}\n"
                        )
                return return_msg.encode()

            return_msg = f"{'Address':<20}{'Type':<12}{'Name':<15}{'Location':<15}{'Connected':<10}\n"
            for value in connected_devices.values():
                return_msg += (
                    f"{value.config_dict['address']:<20}{value.config_dict['type']:<12}{value.config_dict['name']:<15}"
                    f"{value.config_dict['location']:<15}{str(value.is_connected):<10}\n"
                )
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
