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

import soundfile as sf
import librosa

from decoder import Decoder
from packet import *
    
class Process:
    queue = None
    process = None

    def get_queue(self):
        return self.queue
    
    def start(self):
        self.process.start()
    
    def stop(self):
        self.process.terminate()
    
class SoundProcess(Process):
    feature_buffer = {}

    def __init__(self):
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)

        self.buffer = {}

    def _run(self):
        path_base = os.path.dirname(os.path.realpath(__file__))+"/data"

        while True:
            location, device_type, address, service_name, char_name, received_time, data = self.queue.get()

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

                    dir_path = os.path.join(path_base, location, device_type, address, service_name, str(time_dt.strftime("%Y-%m-%d")))
                    try:
                        os.makedirs(dir_path, exist_ok=True)
                    except:
                        pass

                    filename = str(time_dt.strftime("%H:%M:%S")+".npz")

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
    # Process functions ------------------------------------------------------------
    def _save_file_at_dir(self, location, device_type, address, service_name, char_name, received_time, data, mode='a'):
        def swapEndianness(hexstring):
            ba = bytearray.fromhex(hexstring)
            ba.reverse()
            return ba.hex()
        
        path_base = os.path.dirname(os.path.realpath(__file__))+"/data"

        dir_path = os.path.join(path_base, location, device_type, address, service_name)

        try:
            os.makedirs(dir_path, exist_ok=True)
        except:
            pass
        
        time_dt = datetime.fromtimestamp(received_time)
        filename = str(time_dt.strftime("%Y-%m-%d")+".txt")
        # def mqtt_data(f_data):
        #     f_data_i=int(f_data)
        #     f_data_d=int((f_data-int(f_data))*100000)
        #     return str("%04x"%f_data_i), str("%04x"%f_data_d)

        with open(os.path.join(dir_path, filename), mode) as f:
            if service_name == "inference":
                if os.path.getsize(os.path.join(dir_path, filename)) == 0:
                    f.write("time,"
                            "GridEye,Direction,"
                            "ENV,temp,humid,iaq,eco2,bvoc,")
                    f.write("SOUND,"+",".join(self.sound_classlist)+"\n")
                fmt = '<BBBfffff'+'B'+str(self.num_sound_labels)+'b'
                
                # required_bytes = struct.calcsize(fmt)
                inference_unpacked_data = struct.unpack(fmt, data[:24 + self.num_sound_labels])
                file_msg = ','.join(map(str, inference_unpacked_data))
                
                # +128/256
                dequantized_values = [(value + 128) / 256 for value in inference_unpacked_data[-self.num_sound_labels:]]
                dequantized_str = ','.join(map(str, dequantized_values))
                
                file_msg_final = ','.join(map(str, inference_unpacked_data[:-self.num_sound_labels])) + ',' + dequantized_str
                f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S")+","+file_msg_final+"\n")
                    
            else:
                return

    def _run(self):
        while True:            
            location, device_type, address, service_name, char_name, received_time, data = self.queue.get()

            self._save_file_at_dir(location, device_type, address, service_name, char_name, received_time, data)
            
            processed_time = time.time()
            # print(address, 'DATA:', (processed_time-received_time)*1000,'ms')

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

        # print("Mqtt On")
        self.mqtt = self.Mqtt("155.230.186.52", 1883, "csosMember", "csos!1234", "HMK0H001")
        # self.mqtt.connect()
        self.msgq = self.Msgq(6604, sysv_ipc.IPC_CREAT)
    
    def _run(self):
        while True:
            msg_dict = self.queue.get()

            msg_dict.update(SH_ID=self.mqtt.sh_id)

            mqtt_msg_json = json.dumps(msg_dict)
            # print("[MQTT] : " + mqtt_msg_json)

            self.mqtt.publish("/CSOS/ADL/ADLDATA",mqtt_msg_json)