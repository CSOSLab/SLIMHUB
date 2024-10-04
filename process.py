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

import tensorflow_lite as tflite

import paho.mqtt.client as mqtt
import sysv_ipc

import soundfile as sf
import librosa

from decoder import Decoder

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
    DEFAULT_SAMPLE_RATE = 16000
    DEFAULT_UNIT_SAMPLES = 16384

    classlist = ['speech', 'microwave', 'vacuuming', 'tv', 'eating', 'drop', 'smoke_extractor',
                 'cooking', 'dish_clanging', 'peeing', 'chopping', 'water_flowing',
                 'toilet_flushing', 'walking', 'brushing_teeth']

    data_collection_mode = False
    save_in_wav = False

    decoder = Decoder()

    class Buffer:
        def __init__(self):
            self.raw_buffer = []
            self.feature_buffer = []

            # Postprocess buffers
            self.voting_buffer = []

            self.index_before = None
            self.count = np.zeros(len(SoundProcess.classlist))
            self.reliability = np.zeros(len(SoundProcess.classlist))
            self.tolerance = np.zeros(len(SoundProcess.classlist))
            self.start_time = np.zeros(len(SoundProcess.classlist))

            self.result_buffer = []
        
        def clear(self):
            self.raw_buffer.clear()
            self.feature_buffer.clear()
            self.voting_buffer.clear()
            self.result_buffer.clear()

            self.index_before = None
            self.count = np.zeros(len(SoundProcess.classlist))
            self.reliability = np.zeros(len(SoundProcess.classlist))
            self.tolerance = np.zeros(len(SoundProcess.classlist))
            self.start_time = np.zeros(len(SoundProcess.classlist))

    def __init__(self):
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)

        self.sound_sample_rate = self.DEFAULT_SAMPLE_RATE
        self.sound_unit_samples = self.DEFAULT_UNIT_SAMPLES
        self.sound_frame_per_unit = 32
        self.sound_clip_length_sec = 30

        self.result_threshold = 0.6
        self.voting_buffer_len = 7
        self.count_threshold = 4

        self.tolerance = 10

        self.buffer = {}

        self.feature_type = 'mels'

    def save_wav(self, output_path, input, sr):
        sf.write(output_path, input, sr, 'PCM_16')
        # print(output_path, 'saved')

    def get_mfcc(self, input, sr, n_mfcc, n_mels, n_fft, n_hop):
        input_pcm = np.array(input, dtype=np.float32)
        mfcc = librosa.feature.mfcc(y=input_pcm, sr=sr, n_mfcc=n_mfcc, n_mels=n_mels, n_fft=n_fft, hop_length=n_hop)
        mfcc = mfcc[:,:-1]
        mfcc = mfcc[..., np.newaxis]

        return mfcc

    def voting(self, address):
        voting_buffer = np.array(self.buffer[address].voting_buffer)

        vote_result = np.zeros(len(self.classlist))
        reliab_result = np.zeros(len(self.classlist))

        result_index = np.where(voting_buffer > self.result_threshold)[1]
        reliab_index = np.where(voting_buffer > 0)
        reliab_index = zip(reliab_index[0], reliab_index[1])

        for y in result_index:
            vote_result[y] += 1
        for x, y in reliab_index:
            reliab_result[y] += voting_buffer[x,y]
        reliab_result = reliab_result/self.voting_buffer_len

        return vote_result, reliab_result

    def generate_events(self, address, vote, reliab, received_time, end=False, log_path=None, time_dt=None):
        current_buffer = self.buffer[address]

        index = np.where(vote > self.count_threshold)[0]
        
        for idx in index:
            if current_buffer.count[idx] == 0:
                current_buffer.start_time[idx] = received_time
            current_buffer.count[idx] += 1
            current_buffer.reliability[idx] += reliab[idx]

        if current_buffer.index_before is None:
            current_buffer.index_before = index
            return
        
        for idx in current_buffer.index_before:
            if idx not in index or end:
                if current_buffer.tolerance[idx] < self.tolerance and not end:
                    current_buffer.tolerance[idx] += 1
                    index = np.append(index, idx)
                    index = np.unique(index)
                    return
                
                # Event end
                end_time = received_time

                msg = {}
                msg['event'] = self.classlist[idx]
                msg['start_time'] = current_buffer.start_time[idx]
                msg['end_time'] = end_time
                msg['duration'] = (end_time-current_buffer.start_time[idx])*1000
                msg['reliability'] = current_buffer.reliability[idx]/current_buffer.count[idx]
                
                if log_path is not None:
                    with open(os.path.join(log_path, str(time_dt.strftime("%Y-%m-%d_%H"))+".txt"), 'a') as f:
                        f.write(msg['event']+','+str(msg['start_time'])+','+str(msg['end_time'])+','+str(msg['duration'])+','+'%.2f'%msg['reliability']+'\n')

                # print(msg)
                # LogProcess.queue.put(msg)

                current_buffer.start_time[idx] = 0
                current_buffer.reliability[idx] = 0
                current_buffer.count[idx] = 0
                
            else:
                current_buffer.tolerance[idx] = 0

        current_buffer.index_before = index

    def _run(self):
        window_hop = int((self.sound_unit_samples * self.sound_clip_length_sec)/2)

        path_base = os.path.dirname(os.path.realpath(__file__))+"/data"

        while True:
            location, device_type, address, service_name, char_name, received_time, data = self.queue.get()

            path = os.path.join(path_base, location, device_type, address, service_name)

            try:
                os.makedirs(path, exist_ok=True)
            except:
                pass

            time_dt = datetime.fromtimestamp(received_time)

            if address not in self.buffer:
                self.buffer[address] = self.Buffer()
            
            current_buffer = self.buffer[address]

            wav_path = os.path.join(path,"wavfiles")
            byte_path = os.path.join(path,"bytes")
            os.makedirs(wav_path, exist_ok=True)
            os.makedirs(byte_path, exist_ok=True)

            log_path = os.path.join(path,"logs")
            pred_path = os.path.join(path,"predictions")
            os.makedirs(log_path, exist_ok=True)
            os.makedirs(pred_path, exist_ok=True)
            
            if char_name == 'feature':
                try:
                    current_feature_segment = [struct.unpack('<f', data[i:i+4])[0] for i in range(0, len(data), 4)]
                    current_buffer.feature_buffer.extend(current_feature_segment)
                except:
                    continue

                if len(current_buffer.feature_buffer) == 48*32:
                    feature = np.array(current_buffer.feature_buffer, dtype=np.float32).reshape(32,48)
                    print(feature)
                    current_buffer.clear()
            

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