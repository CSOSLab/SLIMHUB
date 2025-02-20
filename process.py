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
import re
import logging
from dataclasses import dataclass

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

import uuid

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
    # sound_classlist = [
    #     'brushing',
    #     'peeing',
    #     'flushing',
    #     'afterflushing',
    #     'airutils',
    #     'hitting',
    #     'microwave',
    #     'cooking',
    #     'speech',
    #     'tv',
    #     'watering1',
    #     'watering2',
    #     'background',
    # ]
    # num_sound_labels = len(sound_classlist)
    
    # these are kitchen-base sound class list
    sound_classlist = [
        'airutils',
        'hitting',
        'microwave',
        'speech',
        'tv',
        'watering1',
        'watering2',
        'background',
        'coffee1',
        'coffee2',
        'purifier',
    ]
    num_sound_labels_kitchen = len(sound_classlist)
                 
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
                    try:
                        debug_string = data.decode('utf-8') if isinstance(data, bytearray) else str(data)
                        debug_dict = json.loads(debug_string)
                        debug_dict["timestamp"] = time_dt.strftime("%Y-%m-%d %H:%M:%S")
                        
                        json.dump(debug_dict, f, ensure_ascii=False)
                        f.write("\n")
                    except json.JSONDecodeError as e:
                        debug_string = data.decode('utf-8') if isinstance(data, bytearray) else str(data)
                        if debug_string.endswith("\n"):
                            f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S") + "," + debug_string)
                        else:
                            f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S") + "," + debug_string + "\n")
                        # logging.log(f"JSONDecodeError: {e}")
                        # logging.log(f"Invalid JSON: {repr(debug_string)}")
                        
                        
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
        # 기존에는 Debug 용 그래프를 사용했지만, 여기서는 residents_house_graph를 unitspace tree로 사용
        self.residents_house_graph = CustomGraph()
        self.residents_house_graph.add_edge("KITCHEN", "ROOM", 5)
        self.residents_house_graph.add_edge("KITCHEN", "BEDROOM", 5)
        self.residents_house_graph.add_edge("ROOM", "BEDROOM", 10)
        # [New code] 초기 활성 노드를 "ROOM"으로 지정 (필요시 변경)
        self.residents_house_graph.set_active_node("ROOM")
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)
        self.ipc_queue = ipc_queue           # [New code] store shared IPC queue
        self.reply_manager = reply_manager   # [New code] store the Manager for reply queues

        # [New code] 초기에는 빈 dictionary로 시작 (address: (location, state))
        self.connected_devices_unitspace_process = {}

    async def _unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        try:
            if service_name == "inference":
                # [New code] 초기 등록 여부 체크:
                if address not in self.connected_devices_unitspace_process:
                    # [New code] 만약 해당 device의 location이 residents_house_graph에 등록되어 있다면,
                    # weak_enter 신호 대신 "ROOM"을 초기 활성 노드로 지정.
                    if location in self.residents_house_graph.nodes:
                        self.connected_devices_unitspace_process[address] = (location, True)
                        # 초기 활성 노드를 "ROOM"으로 설정
                        self.residents_house_graph.set_active_node("ROOM")
                        write_command = ['internal_processing', str(address), "weak_exit"]
                        print(f"[New code] Initial connection for {address} in graph: setting ROOM as active node. (No weak_enter sent)")
                    else:
                        # 만약 location이 graph에 없다면, 기존대로 weak_enter 명령 전송
                        self.connected_devices_unitspace_process[address] = (location, True)
                        write_command = ['internal_processing', str(address), "weak_enter"]
                        print(f"[New code] Initial connection for {address}: sending weak_enter")
                else:
                    # [New code] 이미 등록되어 있는 경우: 기존 state 확인
                    stored_location, current_state = self.connected_devices_unitspace_process[address]
                    received_signal = unpacked_data_list[1]
                    if current_state:  # active 상태
                        if received_signal == 10:
                            # (b) active 상태에서 signal 10 → weak_exit 전송, state inactive로 변경
                            write_command = ['internal_processing', str(address), "weak_exit"]
                            self.connected_devices_unitspace_process[address] = (stored_location, False)
                            print(f"[New code] Active unitspace {address}: received signal 10, sending weak_exit and setting inactive")
                        elif received_signal == 20:
                            # (e) active 상태에서 signal 20 → strong_exit 전송, state inactive로 변경
                            write_command = ['internal_processing', str(address), "strong_exit"]
                            self.connected_devices_unitspace_process[address] = (stored_location, False)
                            print(f"[New code] Active unitspace {address}: received signal 20, sending strong_exit and setting inactive")
                        else:
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
                
                # [New code] 명령 전송 (IPC)
                reply_queue = self.reply_manager.Queue()  # 올바른 reply_manager 사용
                # print("[New code] Sending IPC command:", write_command)
                loop = asyncio.get_running_loop()
                self.ipc_queue.put((write_command, reply_queue))
                result = await loop.run_in_executor(None, reply_queue.get)
                # print("[New code] Received IPC response:", result)
                # [New code] 전달받은 location 정보로 그래프 업데이트:
                self.update_graph_state(address, location)
        except Exception as e:
            print(f"Error: {e}")

    # [New code] graph 상태 업데이트 및 출력: residents_house_graph에 등록된 경우, 활성 노드를 업데이트하고 display_graph() 호출
    def update_graph_state(self, address, new_location):
        if new_location in self.residents_house_graph.nodes:
            # [New code] 새로운 위치가 그래프에 있다면, 기존 활성 노드와 비교
            # 여기서는 단순히 새 위치로 업데이트하는 것으로 처리
            print(f"[New code] Updating graph state for {address}: setting active node to {new_location}")
            self.residents_house_graph.set_active_node(new_location)
            # self.residents_house_graph.display_graph()
            self.residents_house_graph.display_graph_lite()
            # [New code] dictionary의 location 정보도 업데이트
            if address in self.connected_devices_unitspace_process:
                _, current_state = self.connected_devices_unitspace_process[address]
                self.connected_devices_unitspace_process[address] = (new_location, current_state)
        else:
            print(f"[New code] New location {new_location} not found in residents_house_graph.")

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:  # shutdown signal detected
                break
            location, device_type, address, service_name, char_name, received_time, unpacked_data_list = item
            asyncio.run(self._unitspace_existence_estimation(location, device_type, address, service_name, char_name, received_time, unpacked_data_list))
            processed_time = time.time()


            
# class UnitspaceProcess(Process):
#     debug_static_graph = None  # will be initialized in __init__
#     residents_house_graph = None
#     # [New code] dictionary를 address: (location, state) 형식으로 관리 (state: True=active, False=inactive)
#     connected_devices_unitspace_process = {}  

#     # NEW CODE: __init__ now accepts an ipc_queue and a reply_manager
#     def __init__(self, ipc_queue, reply_manager):  # NEW CODE
#         # Initialize the static graph for debugging
#         # Lines below describes how to configure residents' house's unitspace tree graph
#         # For more information, check "customGraphLibrary.py"
#         # self.debug_static_graph = CustomGraph()  # MODIFIED: reinitialize here
#         # self.debug_static_graph.add_edge("TOILET", "LIVING", 3)
#         # self.debug_static_graph.add_edge("TOILET", "KITCHEN", 10)
#         # self.debug_static_graph.add_edge("TOILET", "ROOM", 15)
#         # self.debug_static_graph.add_edge("LIVING", "KITCHEN", 5)
#         # self.debug_static_graph.add_edge("LIVING", "ROOM", 5)
#         # self.debug_static_graph.add_edge("KITCHEN", "ROOM", 10)
#         # self.debug_static_graph.activate_node("LIVING")
#         self.queue = mp.Queue()
#         self.process = mp.Process(target=self._run)
#         self.ipc_queue = ipc_queue                          # store shared IPC queue
#         self.reply_manager = reply_manager                  # store the Manager for reply queues

#         self.residents_house_graph = CustomGraph()
#         self.residents_house_graph.add_edge("KITCHEN", "ROOM", 5)
#         self.residents_house_graph.add_edge("KITCHEN", "BEDROOM", 5)
#         self.residents_house_graph.add_edge("ROOM", "BEDROOM", 10)

#     async def _unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
#         try:
#             if service_name == "inference":
#                 # [New code] 체크: 디바이스가 초기 등록된 경우와 이미 등록된 경우로 구분
#                 if address not in self.connected_devices_unitspace_process:
#                     # [New code] 초기 연결: dictionary에 추가 및 state를 active(True)로 설정, weak_enter 전송
#                     self.connected_devices_unitspace_process[address] = (location, True)
#                     write_command = ['internal_processing', str(address), "weak_enter"]
#                     print(f"[New code] Initial connection for {address}: sending weak_enter")
#                 else:
#                     # [New code] 이미 등록되어 있는 경우: 기존 state 확인
#                     stored_location, current_state = self.connected_devices_unitspace_process[address]
#                     received_signal = unpacked_data_list[1]
#                     # 조건에 따라 명령 및 state 업데이트
#                     if current_state:  # active 상태
#                         print(self.connected_devices_unitspace_process)     #debugging line
#                         print(location)                                     #debugging line
#                         if received_signal == 10:
#                             # (b) active 상태에서 signal 10 → 잘못된 in 신호 → weak_exit 전송, state inactive로 변경
#                             write_command = ['internal_processing', str(address), "weak_exit"]
#                             self.connected_devices_unitspace_process[address] = (stored_location, False)
#                             print(f"[New code] Active unitspace {address}: received signal 10, sending weak_exit and setting inactive")
#                         elif received_signal == 20:
#                             # (e) active 상태에서 signal 20 → strong_exit 전송, state inactive로 변경
#                             write_command = ['internal_processing', str(address), "strong_exit"]
#                             self.connected_devices_unitspace_process[address] = (stored_location, False)
#                             print(f"[New code] Active unitspace {address}: received signal 20, sending strong_exit and setting inactive")
#                         else:
#                             # [New code] 그 외 값이면 default_action (또는 아무 동작 없음)
#                             write_command = ['internal_processing', str(address), "default_action"]
#                             print(f"[New code] Active unitspace {address}: received signal {received_signal}, sending default_action")
#                     else:  # inactive 상태
#                         if received_signal == 10:
#                             # (c) inactive 상태에서 signal 10 → strong_enter 전송, state active로 변경
#                             write_command = ['internal_processing', str(address), "strong_enter"]
#                             self.connected_devices_unitspace_process[address] = (stored_location, True)
#                             print(f"[New code] Inactive unitspace {address}: received signal 10, sending strong_enter and setting active")
#                         elif received_signal == 20:
#                             # (d) inactive 상태에서 signal 20 → weak_enter 전송, state active로 변경
#                             write_command = ['internal_processing', str(address), "weak_enter"]
#                             self.connected_devices_unitspace_process[address] = (stored_location, True)
#                             print(f"[New code] Inactive unitspace {address}: received signal 20, sending weak_enter and setting active")
#                         else:
#                             write_command = ['internal_processing', str(address), "default_action"]
#                             print(f"[New code] Inactive unitspace {address}: received signal {received_signal}, sending default_action")
                
#                 # [New code] 명령 전송
#                 reply_queue = self.reply_manager.Queue()  # NEW CODE: 올바른 reply_manager 사용
#                 print("[New code] Sending IPC command:", write_command)
#                 loop = asyncio.get_running_loop()
#                 self.ipc_queue.put((write_command, reply_queue))
#                 result = await loop.run_in_executor(None, reply_queue.get)
#                 print("[New code] Received IPC response:", result)
#         except Exception as e:
#             print(f"Error: {e}")

#     def _run(self):
#         while True:
#             item = self.queue.get()
#             if item is None:  # MODIFIED: shutdown signal detected
#                 break
#             location, device_type, address, service_name, char_name, received_time, unpacked_data_list = item
#             # [Old code] was using asyncio.run(...) each time
#             asyncio.run(self._unitspace_existence_estimation(location, device_type, address, service_name, char_name, received_time, unpacked_data_list))
#             processed_time = time.time()

class LogProcess(Process):
    MSGQ_TYPE_DEVICE = 1
    MSGQ_TYPE_ENV = 2
    MSGQ_TYPE_SOUND = 3

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
        def __init__(self, ip, port, id, passwd):
            self.ip = ip
            self.port = port
            self.id = id
            self.passwd = passwd
            self.client = mqtt.Client()

        def connect(self):
            self.client.username_pw_set(username=self.id, password=self.passwd)
            self.client.connect(self.ip, self.port)

        def publish(self, topic, message):
            self.client.publish(topic, message)

        def disconnect(self):
            self.client.disconnect()

    def __init__(self):
        self.process = mp.Process(target=self._run)
        self.queue = mp.Queue()
        self.mqtt = self.Mqtt("155.230.186.52", 1883, "csosMember", "csos!1234")
        self.msgq = self.Msgq(6604, sysv_ipc.IPC_CREAT)

    def get_mac_address():
        mac = uuid.getnode()
        return ':'.join(['{:02X}'.format((mac >> i) & 0xff) for i in range(0, 6 * 8, 8)][::-1])

    def _run(self):
         def create_message(category, owner, location, device, activity, action, patient, level):
             return {
                "TIMESTAMP": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "CATEGORY": category,
                "OWNER": owner,
                "KEY": self.get_mac_address(),
                "LOCATION": location,
                "DEVICE": device,
                "ACTIVITY": activity,
                "ACTION": action,
                "PATIENT": patient,
                "LEVEL": level
            }
         
         while True:
            item = self.queue.get()
            if item is None:  # MODIFIED: shutdown signal detected
                break
            location, device_type, address, service_name, char_name, received_time, data = item

            time_dt = datetime.fromtimestamp(received_time)

            if char_name == "debugstr":
                try: 
                    debug_string = data.decode('utf-8') if isinstance(data, bytearray) else str(data)
                    debug_dict = json.loads(debug_string)
                    debug_dict["timestamp"] = time_dt.strftime("%Y-%m-%d %H:%M:%S")

                    mqtt_dict = create_message()
                except json.JSONDecodeError as e:
                    logging.log(f"JSONDecodeError: {e}")
                    logging.log(f"Invalid JSON: {repr(debug_string)}")
                
        # while True:
        #     msg_dict = self.queue.get()
        #     msg_dict.update(SH_ID=self.mqtt.sh_id)
        #     mqtt_msg_json = json.dumps(msg_dict)
        #     self.mqtt.publish("/CSOS/ADL/ADLDATA", mqtt_msg_json)
