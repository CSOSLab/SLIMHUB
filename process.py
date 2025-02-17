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
                    debug_dict = json.loads(debug_string)
                    debug_dict["timestamp"] = time_dt.strftime("%Y-%m-%d %H:%M:%S")
                    
                    json.dump(debug_dict, f, ensure_ascii=False)
                    f.write("\n")
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
        self.ipc_queue = ipc_queue  # NEW CODE: store shared IPC queue
        self.reply_manager = reply_manager  # NEW CODE: store the Manager for reply queues
        
        self.residents_house_graph = CustomGraph()
    
    async def _unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        try:
            if service_name == "inference":
                print(self.connected_devices_unitspace_process)
                if not address in self.connected_devices_unitspace_process:
                    # Frist unitspace moving signal from DEAN node
                    if location == "undefined":
                        print("Unitspace signal from undefined dean node : " + str(address))
                    self.connected_devices_unitspace_process.update({address, location})
                    received_signal = unpacked_data_list[1]
                    write_command = ['internal_processing' , str(address), "default_action"]
                    if received_signal == 10:      # 10 is "in" signal
                        print("signal -> [ IN ] to " + location)
                        write_command = ['internal_processing' , str(address), "strong_enter"]
                    elif received_signal == 20:
                        print("signal -> [ OUT ] to " + location)
                        write_command = ['internal_processing' , str(address), "strong_exit"]
                    reply_queue = self.replay_manager.Queue()       # Send ble write command to device queue
                    loop = asyncio.get_running_loop()
                    self.ipc_queue.put((write_command, reply_queue))
                    result = await loop.run_in_executor(None, reply_queue.get)
                    if result is None:
                        print("IPC response not reached.")
                else:
                    if location == "undefined":
                        print("Unitspace signal from undefined dean node")
                
                
                # current_active_unitspace = self.debug_static_graph.get_active_nodes()
                # in_out_check = unpacked_data_list[1]        
                # if in_out_check == 10:
                #     print("Signal -> [ IN ] to: " + location)
                # elif in_out_check == 20:
                #     print("Signal -> [ OUT ] from: " + location)
                # if location not in current_active_unitspace:
                #     self.debug_static_graph.activate_node(location)
                #     self.debug_static_graph.deactivate_node(current_active_unitspace[0])
                #     print("Resident moved: {} to {}".format(current_active_unitspace[0], self.debug_static_graph.get_active_nodes()))
                #     print("Current activated unitspace: " + str(self.debug_static_graph.get_active_nodes()))
                
                # NEW CODE: Send command via IPC to DeviceManager using a reply queue from reply_manager
                write_command = ['internal_processing', str(address), "strong_true"]
                reply_queue = self.reply_manager.Queue()  # NEW CODE: Use reply_manager.Queue() instead of mp.Queue()
                # logging.info("Sending IPC command: ", write_command)
                print("Sending IPC command:", write_command)
                loop = asyncio.get_running_loop()
                self.ipc_queue.put((write_command, reply_queue))
                # Wait for reply without blocking the event loop
                result = await loop.run_in_executor(None, reply_queue.get)
                print("Received IPC response:", result)
                # logging.info("Received IPC reponse: ", result)
                
        except Exception as e:
            print(f"Error: {e}")
    
    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:  # MODIFIED: shutdown signal detected
                break
            location, device_type, address, service_name, char_name, received_time, unpacked_data_list = item
            asyncio.run(self._unitspace_existence_estimation(location, device_type, address, service_name, char_name, received_time, unpacked_data_list))
            processed_time = time.time()

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
            self.client = mqtt.Client("")

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
                debug_string = data.decode('utf-8') if isinstance(data, bytearray) else str(data)
                debug_dict = json.loads(debug_string)
                debug_dict["timestamp"] = time_dt.strftime("%Y-%m-%d %H:%M:%S")

                mqtt_dict = create_message()
                
        # while True:
        #     msg_dict = self.queue.get()
        #     msg_dict.update(SH_ID=self.mqtt.sh_id)
        #     mqtt_msg_json = json.dumps(msg_dict)
        #     self.mqtt.publish("/CSOS/ADL/ADLDATA", mqtt_msg_json)
