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

import paho.mqtt.client as mqtt
import sysv_ipc
import queue  # MODIFIED: for Empty exception in manager_main (if needed)

import soundfile as sf
import librosa

from decoder import Decoder
from packet import *
from dean_uuid import *

import uuid

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
num_sound_labels = len(sound_classlist)

env_list = [
    'temperature',
    'humidity',
    'IAQ',
    'CO2',
    'bVOC',
]

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
        path_base = os.path.join(os.path.dirname(os.path.realpath(__file__)), "programdata", "datasets")
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
                    dir_path = os.path.join(path_base, address, "features", time_dt.strftime("%Y-%m-%d"))
                    try:
                        os.makedirs(dir_path, exist_ok=True)
                    except:
                        pass
                    filename = time_dt.strftime("%H:%M:%S") + ".npz"
                    # save to npz
                    np.savez(os.path.join(dir_path, filename), feature=feature)
                    self.buffer[address] = []
            
from collections import deque
import os
from datetime import datetime
import statistics

row_history = [deque(maxlen=10) for _ in range(8)]
col_history = [deque(maxlen=10) for _ in range(8)]

row_x_index_queue = deque(maxlen=20)
col_x_index_queue = deque(maxlen=20)

threshold_multiplier = 4.0  # <- 여기를 1.5, 3.0 등으로 조절 가능

class DataProcess(Process):
    def __init__(self):
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)

    def _rawdata_result_handling_func(self, location, device_type, address, service_name, char_name, received_time, data, mode='a'):
        path_base = os.path.join(os.path.dirname(os.path.realpath(__file__)), "data")
        dir_path = os.path.join(path_base, location, device_type, address, service_name, char_name)

        try:
            os.makedirs(dir_path, exist_ok=True)
        except:
            pass

        time_dt = datetime.fromtimestamp(received_time)
        raw_filename = time_dt.strftime("%Y-%m-%d") + ".txt"
        raw_path = os.path.join(dir_path, raw_filename)

        if service_name == "grideye" and char_name == "raw":
            try:
                if not isinstance(data, (bytes, bytearray)) or len(data) != 260:
                    with open(raw_path, mode) as f:
                        f.write(f"{time_dt.strftime('%H:%M:%S')}, Error: invalid grideye data length ({len(data)} bytes)\n")
                    return

                # 64개의 int32 값
                values = [int.from_bytes(data[i:i+4], byteorder='little') for i in range(0, 64 * 4, 4)]
                threshold = int.from_bytes(data[256:260], byteorder='little')
                timestamp = time_dt.strftime("%H:%M:%S")

                # 8x8 grid 구성 + 상하 반전
                grid = [values[i:i+8] for i in range(0, 64, 8)][::-1]

                # Row/Column 합 계산
                row_sums = [sum(row) for row in grid]
                col_sums = [sum(col) for col in zip(*grid)]
                max_row_sum = max(row_sums)
                max_col_sum = max(col_sums)

                # 이상치 감지
                row_flags = []
                col_flags = []

                for i, val in enumerate(row_sums):
                    hist = row_history[i]
                    if len(hist) >= 2:
                        mean = sum(hist) / len(hist)
                        std = (sum((x - mean) ** 2 for x in hist) / len(hist)) ** 0.5
                        row_flags.append(abs(val - mean) > threshold_multiplier * std)
                    else:
                        row_flags.append(False)
                    hist.append(val)

                for i, val in enumerate(col_sums):
                    hist = col_history[i]
                    if len(hist) >= 2:
                        mean = sum(hist) / len(hist)
                        std = (sum((x - mean) ** 2 for x in hist) / len(hist)) ** 0.5
                        col_flags.append(abs(val - mean) > threshold_multiplier * std)
                    else:
                        col_flags.append(False)
                    hist.append(val)

                any_row_change = any(row_flags)
                any_col_change = any(col_flags)

                # X 인덱스 기록
                x_row_index = None
                if any_row_change:
                    row_deltas = [
                        abs(row_sums[i] - (sum(row_history[i]) / len(row_history[i])))
                        if row_flags[i] else -1
                        for i in range(8)
                    ]
                    x_row_index = row_deltas.index(max(row_deltas))
                row_x_index_queue.append(x_row_index)

                x_col_index = None
                if any_col_change:
                    col_deltas = [
                        abs(col_sums[i] - (sum(col_history[i]) / len(col_history[i])))
                        if col_flags[i] else -1
                        for i in range(8)
                    ]
                    x_col_index = col_deltas.index(max(col_deltas))
                col_x_index_queue.append(x_col_index)

                with open(raw_path, mode) as f:
                    f.write(f"{timestamp}, threshold: {threshold}\n")

                    # ✅ 행 출력
                    for i, row in enumerate(grid):
                        row_sum = row_sums[i]
                        row_std = statistics.stdev(row_history[i]) if len(row_history[i]) > 1 else 0  # ✅ 시간 기준

                        row_str = "".join(f"{v:>7d}" for v in row)

                        mark = ""
                        if any_row_change:
                            if row_sum == max_row_sum:
                                mark = "  X"
                            elif row_flags[i]:
                                mark = "  *"

                        summary = f"\t{row_sum:5d} {row_std:6.1f}"
                        f.write(row_str + mark + summary + "\n")

                    # ✅ 열 출력
                    col_sum_line = ""
                    col_std_line = ""
                    col_mark_line = ""

                    for i in range(8):
                        c_sum = col_sums[i]
                        c_std = statistics.stdev(col_history[i]) if len(col_history[i]) > 1 else 0  # ✅ 시간 기준

                        # 마크: 변화 감지 + 최대값
                        if any_col_change:
                            if c_sum == max_col_sum:
                                col_mark_line += f"{'X':>7}"
                            elif col_flags[i]:
                                col_mark_line += f"{'*':>7}"
                            else:
                                col_mark_line += " " * 7
                        else:
                            col_mark_line += " " * 7

                        col_sum_line += f"{c_sum:7d}"
                        col_std_line += f"{c_std:7.1f}"

                    f.write(col_mark_line + "\n\n")
                    f.write(col_sum_line + "\n")
                    f.write(col_std_line + "\n\n")

                    # X 인덱스 히스토리 출력
                    f.write("row_X_history: " + str(list(row_x_index_queue)) + "\n")
                    f.write("col_X_history: " + str(list(col_x_index_queue)) + "\n\n")

            except Exception as e:
                with open(raw_path, mode) as f:
                    f.write(f"{time_dt.strftime('%H:%M:%S')}, Error parsing grideye data: {e}\n")

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:  # MODIFIED: shutdown signal detected
                break
            location, device_type, address, service_name, char_name, received_time, data = item
            self._rawdata_result_handling_func(location, device_type, address, service_name, char_name, received_time, data)


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
        super().__init__()
        self.process = mp.Process(target=self._run)
        self.queue = mp.Queue()
        self.mqtt = self.Mqtt("155.230.186.52", 1883, "csosMember", "csos!1234")
        self.msgq = self.Msgq(6604, sysv_ipc.IPC_CREAT)

    def get_mac_address(self):
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
            if item is None:  # shutdown signal detected
                break
 
            location, device_type, address, service_name, char_name, received_time, data = item

            time_dt = datetime.fromtimestamp(received_time)

            # 경로 설정
            filename = time_dt.strftime("%Y-%m-%d") + ".txt"
            path_base = os.path.join(os.path.dirname(os.path.realpath(__file__)), "data")
            # dir_path = os.path.join(path_base, location, device_type, address, service_name, "display")
            dir_path = os.path.join(path_base, "display")

            # 디렉터리 생성
            os.makedirs(dir_path, exist_ok=True)

            # 디버그 문자열 처리
            if char_name == "debugstr":
                try:
                    debug_string = data.decode('utf-8') if isinstance(data, bytearray) else str(data)
                    debug_dict = json.loads(debug_string)
                    debug_dict["timestamp"] = time_dt.strftime("%Y-%m-%d %H:%M:%S")
                    timestamp = debug_dict["timestamp"]

                    log_message = ""
                    
                    # SOUND 이벤트 처리 (ID 1과 7 무시)
                    if debug_dict['type'] == 'DEBUG' and debug_dict['event'] == 'SOUND':
                        label = debug_dict.get('id', 'unknown')
                        if label not in ("unknown", "background"):
                            log_message = f"{timestamp}  {location} [EVENT] - Sound '{label}' was detected\n"

                    # ENV 이벤트 처리
                    elif debug_dict['type'] == 'DEBUG' and debug_dict['event'] == 'ENV':
                        env_id = debug_dict.get('id', -1)
                        label = env_list[env_id] if 0 <= env_id < len(env_list) else "N/A"
                        log_message = f"{timestamp}  {location} [EVENT] - '{label}' event was detected\n"
                    
                    # ENTER 이벤트 처리
                    elif debug_dict['type'] == 'DEBUG' and debug_dict['event'] == 'ENTER':
                        value = debug_dict.get('value', 0)
                        log_message = f"{timestamp}  {location} [EVENT] - ENTER value: {value}\n"

                    # EXIT 이벤트 처리
                    elif debug_dict['type'] == 'DEBUG' and debug_dict['event'] == 'EXIT':
                        value = debug_dict.get('value', 0)
                        log_message = f"{timestamp}  {location} [EVENT] - EXIT value: {value}\n"

                    # INFERENCE 처리
                    elif debug_dict['type'] == 'INFERENCE':
                        status = debug_dict.get('status', '')
                        adl = debug_dict.get('ADL', 'N/A')
                        sequence = debug_dict.get('sequence', 'N/A')
                        truth = debug_dict.get('truth', 0.0)
                        missing = debug_dict.get('missing', 'None')
                        value = debug_dict.get('value', 0)
                        
                        if status == 'EXCEPTION':
                            log_message = f"{timestamp}  {location} [INFERENCE] {status}: {adl}, value: {value}\n"

                        else:
                            log_message = f"{timestamp}  {location} [INFERENCE] {status}: {adl}, sequence: {sequence}, truth: {truth:.2f}, missing: {missing}\n"
                            
                    # PRIORITY HEAP 처리
                    elif debug_dict['type'] == 'HEAPPRINT':
                        heap_state_str = debug_dict.get('heap_state', '')
                        log_message = f"{timestamp} {location} [HEAP STATE] - {heap_state_str}"

                    # 로그 파일에 기록
                    if log_message:
                        with open(os.path.join(dir_path, filename), 'a') as f:
                            f.write(log_message)
                            
                    # print(log_message)      # for debugging - display one

                except json.JSONDecodeError as e:
                    logging.error(f"JSONDecodeError: {e}")
                    logging.error(f"Invalid JSON: {repr(debug_string)}")
                except IndexError as e:
                    logging.error(f"IndexError: {e} - Sound ID out of range")
                except KeyError as e:
                    logging.error(f"KeyError: {e}")
                except Exception as e:
                    logging.error(f"Unexpected error: {e}")

                # mqtt_dict = create_message()
            
        # while True:
        #     msg_dict = self.queue.get()
        #     msg_dict.update(SH_ID=self.mqtt.sh_id)
        #     mqtt_msg_json = json.dumps(msg_dict)
        #     self.mqtt.publish("/CSOS/ADL/ADLDATA", mqtt_msg_json)


# Depricated
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
        self.residents_house_graph.add_edge("ENTRY", "KITCHEN", 15)
        self.residents_house_graph.add_edge("ENTRY", "ROOM", 20)
        self.residents_house_graph.add_edge("ENTRY", "BEDROOM", 15)
        # [New code] 초기 활성 노드를 "ROOM"으로 지정 (필요시 변경)
        self.residents_house_graph.set_active_node("ENTRY")
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)
        self.ipc_queue = ipc_queue           # [New code] store shared IPC queue
        self.reply_manager = reply_manager   # [New code] store the Manager for reply queues

        # [New code] 초기에는 빈 dictionary로 시작 (address: (location, state))
        self.connected_devices_unitspace_process = {}

    async def _unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        time_dt = datetime.fromtimestamp(received_time)
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
                self.update_graph_state(address, location, time_dt)
        except Exception as e:
            print(f"Error: {e}")

    # [New code] graph 상태 업데이트 및 출력: residents_house_graph에 등록된 경우, 활성 노드를 업데이트하고 display_graph() 호출
    def update_graph_state(self, address, new_location, time_dt):
        if new_location in self.residents_house_graph.nodes:
            # [New code] 새로운 위치가 그래프에 있다면, 기존 활성 노드와 비교
            # 여기서는 단순히 새 위치로 업데이트하는 것으로 처리
            print(f"[New code] Updating graph state for {address}: setting active node to {new_location}")
            self.residents_house_graph.set_active_node(new_location)
            # self.residents_house_graph.display_graph()
            self.residents_house_graph.display_graph_lite(time_dt)
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