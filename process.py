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
import logging
from dataclasses import dataclass

import tensorflow_lite as tflite

import paho.mqtt.client as mqtt
import sysv_ipc
import queue  # MODIFIED: for Empty exception in manager_main (if needed)

import soundfile as sf
import librosa

from decoder import Decoder
from packet import *
from customGraphLibrary import *
import device
from dean_uuid import *

# Base Process class
class Process:
    queue = None
    process = None

    def get_queue(self):
        return self.queue
    
    def start(self):
        self.process.start()
    
    def stop(self):
        # MODIFIED: Instead of terminating the process, send a shutdown signal via the queue
        if self.queue is not None:
            self.queue.put(None)

class SoundProcess(Process):
    feature_buffer = {}

    def __init__(self):
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)
        self.buffer = {}

    def _run(self):
        path_base = os.path.join(os.path.dirname(os.path.realpath(__file__)), "data")
        while True:
            item = self.queue.get()
            if item is None:  # MODIFIED: shutdown signal detected
                break
            location, device_type, address, service_name, char_name, received_time, data = item
            time_dt = datetime.fromtimestamp(received_time)
            data_packet = SoundFeaturePacket.unpack(data)
            if address not in self.buffer:
                self.buffer[address] = []
            if data_packet.cmd == FEATURE_COLLECTION_CMD_DATA:
                self.buffer[address].append(data_packet.data)
            elif data_packet.cmd == FEATURE_COLLECTION_CMD_FINISH:
                # save buffer to file
                if len(self.buffer[address]) > 0:
                    feature = np.array(self.buffer[address])
                    dir_path = os.path.join(path_base, location, device_type, address, service_name, time_dt.strftime("%Y-%m-%d"))
                    try:
                        os.makedirs(dir_path, exist_ok=True)
                    except:
                        pass
                    filename = time_dt.strftime("%H:%M:%S") + ".npz"
                    # save to npz
                    np.savez(os.path.join(dir_path, filename), feature=feature)
                    self.buffer[address] = []
            

class DataProcess(Process):
    sound_classlist = [
        'brushing',
        'peeing',
        'flushing',
        'afterflushing',
        'airutils',
        'hitting',
        'microwave',
        'cooking',
        'speech',
        'tv',
        'watering1',
        'watering2',
        'background',
    ]
    num_sound_labels = len(sound_classlist)
                 
    def __init__(self):
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)
    
    def _rawdata_result_handling_func(self, location, device_type, address, service_name, char_name, received_time, data, mode='a'):
        def swapEndianness(hexstring):
            ba = bytearray.fromhex(hexstring)
            ba.reverse()
            return ba.hex()
        
        path_base = os.path.join(os.path.dirname(os.path.realpath(__file__)), "data")
        dir_path = os.path.join(path_base, location, device_type, address, service_name, char_name)
        try:
            os.makedirs(dir_path, exist_ok=True)
        except:
            pass
        time_dt = datetime.fromtimestamp(received_time)
        filename = time_dt.strftime("%Y-%m-%d") + ".txt"
        with open(os.path.join(dir_path, filename), mode) as f:
            if service_name == "inference":
                if char_name == "rawdata":
                    if os.path.getsize(os.path.join(dir_path, filename)) == 0:
                        f.write("time,GridEye,Direction,ENV,temp,humid,iaq,eco2,bvoc,")
                        f.write("SOUND," + ",".join(self.sound_classlist) + "\n")
                    fmt = '<BBBfffff' + 'B' + str(self.num_sound_labels) + 'b'
                    inference_unpacked_data = struct.unpack(fmt, data[:24 + self.num_sound_labels])
                    file_msg = ','.join(map(str, inference_unpacked_data))
                    dequantized_values = [(value + 128) / 256 for value in inference_unpacked_data[-self.num_sound_labels:]]
                    dequantized_str = ','.join(map(str, dequantized_values))
                    file_msg_final = ','.join(map(str, inference_unpacked_data[:-self.num_sound_labels])) + ',' + dequantized_str
                    f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S") + "," + file_msg_final + "\n")
                elif char_name == "debugstr":
                    debug_string = data.decode('utf-8') if isinstance(data, bytearray) else str(data)
                    if debug_string.endswith("\n"):
                        f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S") + "," + debug_string)
                    else:
                        f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S") + "," + debug_string + "\n")
            else:
                return
            
    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:  # MODIFIED: shutdown signal detected
                break
            location, device_type, address, service_name, char_name, received_time, data = item
            self._rawdata_result_handling_func(location, device_type, address, service_name, char_name, received_time, data)
            processed_time = time.time()
            
class UnitspaceProcess(Process):
    debug_static_graph = None  # will be initialized in __init__
    residents_house_graph = None
    # [New code] dictionary를 address: (location, state) 형식으로 관리 (state: True=active, False=inactive)
    connected_devices_unitspace_process = {}  

    # NEW CODE: __init__ now accepts an ipc_queue and a reply_manager
    def __init__(self, ipc_queue, reply_manager):  # NEW CODE
        # Initialize the static graph
        self.debug_static_graph = CustomGraph()  # MODIFIED: reinitialize here
        self.debug_static_graph.add_edge("TOILET", "LIVING", 3)
        self.debug_static_graph.add_edge("TOILET", "KITCHEN", 10)
        self.debug_static_graph.add_edge("TOILET", "ROOM", 15)
        self.debug_static_graph.add_edge("LIVING", "KITCHEN", 5)
        self.debug_static_graph.add_edge("LIVING", "ROOM", 5)
        self.debug_static_graph.add_edge("KITCHEN", "ROOM", 10)
        self.debug_static_graph.activate_node("LIVING")
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)
        self.ipc_queue = ipc_queue                          # store shared IPC queue
        self.reply_manager = reply_manager                  # store the Manager for reply queues

        self.residents_house_graph = CustomGraph()

    async def _unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        try:
            if service_name == "inference":
                # [New code] 체크: 디바이스가 초기 등록된 경우와 이미 등록된 경우로 구분
                if address not in self.connected_devices_unitspace_process:
                    # [New code] 초기 연결: dictionary에 추가 및 state를 active(True)로 설정, weak_enter 전송
                    self.connected_devices_unitspace_process[address] = (location, True)
                    write_command = ['internal_processing', str(address), "weak_enter"]
                    print(f"[New code] Initial connection for {address}: sending weak_enter")
                else:
                    # [New code] 이미 등록되어 있는 경우: 기존 state 확인
                    stored_location, current_state = self.connected_devices_unitspace_process[address]
                    received_signal = unpacked_data_list[1]
                    # 조건에 따라 명령 및 state 업데이트
                    if current_state:  # active 상태
                        if received_signal == 10:
                            # (b) active 상태에서 signal 10 → 잘못된 in 신호 → weak_exit 전송, state inactive로 변경
                            write_command = ['internal_processing', str(address), "weak_exit"]
                            self.connected_devices_unitspace_process[address] = (stored_location, False)
                            print(f"[New code] Active unitspace {address}: received signal 10, sending weak_exit and setting inactive")
                        elif received_signal == 20:
                            # (e) active 상태에서 signal 20 → strong_exit 전송, state inactive로 변경
                            write_command = ['internal_processing', str(address), "strong_exit"]
                            self.connected_devices_unitspace_process[address] = (stored_location, False)
                            print(f"[New code] Active unitspace {address}: received signal 20, sending strong_exit and setting inactive")
                        else:
                            # [New code] 그 외 값이면 default_action (또는 아무 동작 없음)
                            write_command = ['internal_processing', str(address), "default_action"]
                            print(f"[New code] Active unitspace {address}: received signal {received_signal}, sending default_action")
                    else:  # inactive 상태
                        if received_signal == 10:
                            # (c) inactive 상태에서 signal 10 → strong_enter 전송, state active로 변경
                            write_command = ['internal_processing', str(address), "strong_enter"]
                            self.connected_devices_unitspace_process[address] = (stored_location, True)
                            print(f"[New code] Inactive unitspace {address}: received signal 10, sending strong_enter and setting active")
                        elif received_signal == 20:
                            # (d) inactive 상태에서 signal 20 → weak_enter 전송, state active로 변경
                            write_command = ['internal_processing', str(address), "weak_enter"]
                            self.connected_devices_unitspace_process[address] = (stored_location, True)
                            print(f"[New code] Inactive unitspace {address}: received signal 20, sending weak_enter and setting active")
                        else:
                            write_command = ['internal_processing', str(address), "default_action"]
                            print(f"[New code] Inactive unitspace {address}: received signal {received_signal}, sending default_action")
                
                # [New code] 명령 전송
                reply_queue = self.reply_manager.Queue()  # NEW CODE: 올바른 reply_manager 사용
                print("[New code] Sending IPC command:", write_command)
                loop = asyncio.get_running_loop()
                self.ipc_queue.put((write_command, reply_queue))
                result = await loop.run_in_executor(None, reply_queue.get)
                print("[New code] Received IPC response:", result)
        except Exception as e:
            print(f"Error: {e}")

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:  # MODIFIED: shutdown signal detected
                break
            location, device_type, address, service_name, char_name, received_time, unpacked_data_list = item
            # [Old code] was using asyncio.run(...) each time
            asyncio.run(self._unitspace_existence_estimation(location, device_type, address, service_name, char_name, received_time, unpacked_data_list))
            processed_time = time.time()

class LogProcess(Process):
    MSGQ_TYPE_DEVICE = 1
    MSGQ_TYPE_ENV = 2
    MSGQ_TYPE_SOUND = 3

    queue = mp.Queue()

    class Msgq():
        def __init__(self, key_t, flag):
            self.key_t = key_t
            self.flag = flag
            self.MessageQueue = sysv_ipc.MessageQueue(key_t, flag)
        
        def send(self, payload, msg_type):
            self.MessageQueue.send(payload, True, type=msg_type)
        
        def recv(self):
            self.MessageQueue.receive()

    class Mqtt():
        def __init__(self, ip, port, id, passwd, sh_id):
            self.ip = ip
            self.port = port
            self.id = id
            self.passwd = passwd
            self.client = mqtt.Client("")
            self.sh_id = sh_id

        def connect(self):
            self.client.username_pw_set(username=self.id, password=self.passwd)
            self.client.connect(self.ip, self.port)

        def publish(self, topic, message):
            self.client.publish(topic, message)

        def disconnect(self):
            self.client.disconnect()

    def __init__(self):
        self.process = mp.Process(target=self._run)
        self.mqtt = self.Mqtt("155.230.186.52", 1883, "csosMember", "csos!1234", "HMK0H001")
        self.msgq = self.Msgq(6604, sysv_ipc.IPC_CREAT)
    
    def _run(self):
        while True:
            msg_dict = self.queue.get()
            msg_dict.update(SH_ID=self.mqtt.sh_id)
            mqtt_msg_json = json.dumps(msg_dict)
            self.mqtt.publish("/CSOS/ADL/ADLDATA", mqtt_msg_json)
