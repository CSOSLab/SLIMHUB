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
    
    # TFLite functions ------------------------------------------------------------
    def set_env_sound_interpreter(self, model_path):
        self.env_interpreter = tflite.set_interpreter(model_path)

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

            if char_name == 'processed':
                self.data_collection_mode = False
            elif char_name == 'raw':
                self.data_collection_mode = True

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
            
            if self.data_collection_mode:
                # Mic stop trigger packet: save wav and clear buffer
                if data == b'\xff\xff\xff\xff':
                    if self.save_in_wav:
                        self.save_wav(os.path.join(wav_path, str(time_dt.strftime("%Y-%m-%d_%H-%M-%S"))+".wav"), current_buffer.raw_buffer, self.sound_sample_rate)
                        current_buffer.raw_buffer.clear()
                    else:
                        with open(os.path.join(byte_path, str(time_dt.strftime("%Y-%m-%d_%H-%M-%S"))+".dat"), "wb") as f:
                            f.write(bytearray(current_buffer.raw_buffer))
                        current_buffer.raw_buffer.clear()
                    continue

                if self.save_in_wav:
                    pcm = self.decoder.adpcm_decode(data)

                    current_buffer.raw_buffer.extend(pcm)
                    
                    # Save wav files every 'sound_clip_length_sec' sec
                    if len(current_buffer.raw_buffer) >= (self.sound_unit_samples * self.sound_clip_length_sec):
                        self.save_wav(os.path.join(wav_path, str(time_dt.strftime("%Y-%m-%d_%H-%M-%S"))+".wav"), current_buffer.raw_buffer, self.sound_sample_rate)
                        current_buffer.raw_buffer.clear()
                else:
                    current_buffer.raw_buffer.extend(data)

                    if(len(current_buffer.raw_buffer) >= (len(data) * self.sound_frame_per_unit * self.sound_clip_length_sec)):
                        with open(os.path.join(byte_path, str(time_dt.strftime("%Y-%m-%d_%H-%M-%S"))+".dat"), "wb") as f:
                            f.write(bytearray(current_buffer.raw_buffer))
                        current_buffer.raw_buffer.clear()

                # Process time check
                # processed_time = time.time()
                # print(address, 'SOUND:', (processed_time-received_time)*1000,'ms')
                    
            else:
                # Mic stop trigger packet: save wav and clear buffer
                if data == b'\xff\xff\xff\xff':
                    self.generate_events(address, post[0], post[1], received_time, end=True, log_path=log_path, time_dt=time_dt)
                    current_buffer.clear()
                    continue

                try:
                    if self.feature_type == 'mfcc':
                        current_buffer.feature_buffer.append([struct.unpack('<f', data[i:i+4])[0] for i in range(0, len(data), 4)])
                    elif self.feature_type == 'mels':
                        current_buffer.feature_buffer.append(np.array(data, dtype=np.uint8))
                except:
                    continue
                
                if len(current_buffer.feature_buffer) == self.sound_frame_per_unit:
                    try:
                        if self.feature_type == 'mfcc':
                            result = tflite.inference(self.env_interpreter, np.array(current_buffer.feature_buffer, dtype=np.float32).T[..., np.newaxis])
                        elif self.feature_type == 'mels':
                            result = tflite.inference(self.env_interpreter, np.array(current_buffer.feature_buffer, dtype=np.uint8).T[..., np.newaxis])
                            result = result/256.0
                    except Exception as e:
                        logging.warning(e)
                        continue

                    # Save raw inference result
                    log_time = str(time_dt.strftime("%Y-%m-%d %H:%M:%S"))
                    with open(os.path.join(pred_path, str(time_dt.strftime("%Y-%m-%d_%H"))+".txt"), 'a') as f:
                        f.write(log_time+','+','.join(result.astype(str))+'\n')

                    # Postprocessing
                    current_buffer.voting_buffer.append(result)
                    if len(current_buffer.voting_buffer) == self.voting_buffer_len:
                        post = self.voting(address)
                        self.generate_events(address, post[0], post[1], received_time)
                        # Todo: Postprocessing
                        # buf = np.array(current_buffer.voting_buffer).swapaxes(0, 1)
                        # counts = np.sum(buf > self.result_threshold, axis=1)
                        # idxs = np.where(counts != 0)[0]
                        # for idx in idxs:
                        #     mean = np.mean(buf[idx][buf[idx] > self.result_threshold])
                        #     f_logs.write(log_time+','+self.classlist[idx]+','+str(counts[idx])+','+'%.2f'%mean+'\n')
                        
                        # Process time check
                        processed_time = time.time()
                        # print(address, 'SOUND:', (processed_time-received_time)*1000,'ms')

                        current_buffer.voting_buffer = current_buffer.voting_buffer[1:]
                        
                    current_buffer.feature_buffer = current_buffer.feature_buffer[int(self.sound_frame_per_unit/2):]

class DataProcess(Process):
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
            if service_name == "grideye":
                if os.path.getsize(os.path.join(dir_path, filename)) == 0:
                    f.write("time,action\n")
                grideye_msg = ""
                grideye_unpacked = struct.unpack("<B", data)
                grideye_msg = grideye_msg+str(grideye_unpacked)
                # f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S")+","+str(grideye_msg)+"\n")
                grideye_msg = grideye_msg.replace("(", "").replace(")", "")
                grideye_msg = grideye_msg.replace(",,", ",")
                f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S")+","+grideye_msg+"\n")

                # mqtt_msg_dict = {}
                # mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                # mqtt_msg_dict.update(location=self.device_location)
                # mqtt_msg_dict.update(time=time_dt.strftime("%Y-%m-%d %H:%M:%S"))
                # mqtt_msg_dict.update(grideye_raw=grideye_msg)
                # mqtt_msg_json = json.dumps(mqtt_msg_dict)
                # self.mqtt.publish("/CSOS/ADL/ADLDATA",mqtt_msg_json)
                
                # # packing data into Device's Signal
                # msgq_payload_device_signal = ""
                # # msgq_payload_device_signal = msgq_payload_device_signal+str(grideye_msg)
                # msgq_payload_device_signal = msgq_payload_device_signal+"SJK,"+str(self.device_location)+","+str(grideye_msg[:2])+",,,,,,,,"+"\n"
                # self.msgq.send(msgq_payload_device_signal, MSGQ_TYPE_DEVICE)

                # mqtt_msg_dict = {}

            elif service_name == "aat":
                aat_msg = ""
                aat_unpacked = struct.unpack("<BBBBBBBBBB", data)
                aat_msg = aat_msg+str(aat_unpacked)
                # f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S")+","+str(aat_msg)+"\n")
                aat_msg = aat_msg.replace("(", "").replace(")", "")
                aat_msg = aat_msg.replace(",,", ",")
                f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S")+","+aat_msg+"\n")

                found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/AAT"))]
                # mqtt_msg_dict = {}
                # mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                # mqtt_msg_dict.update(location=found_location)
                # mqtt_msg_dict.update(time=time_dt.strftime("%Y-%m-%d %H:%M:%S"))
                # # mqtt_msg_dict.update(aat=)

            elif service_name == "environment":
                if os.path.getsize(os.path.join(dir_path, filename)) == 0:
                    f.write("time,press,temp,humid,gas_raw,iaq,s_iaq,eco2,bvoc,gas_percent,clear\n")
                # data_str=str(file_content[0])+"."+str(file_content[1])+","+\
                # str(file_content[2])+"."+str(file_content[3])+","+\
                # str(file_content[4])+"."+str(file_content[5])+","+\
                # str(file_content[6])+"."+str(file_content[7])
                file_msg = ""
                log_msg = ""
                for i in range(9):
                    temp_msg = struct.unpack('<f', data[4*i:4*(i+1)])
                    file_msg = file_msg+str(temp_msg)+","
                    temp_msg = str(temp_msg).replace("(", "").replace(",)", "")
                    log_msg = log_msg+format(float(temp_msg), '.3f')+","
                file_msg = file_msg.replace("(", "").replace(")", "")
                file_msg = file_msg.replace(",,", ",")
                log_msg = log_msg.replace("(", "").replace(")", "")
                log_msg = log_msg.replace(",,", ",")

                # mqtt_msg=press_i+press_d+temp_i+temp_d+humid_i+gas_raw_i+eco2_i+bvoc_i+red+green+blue+clear
                # message="{\"HEADER\":{\"PAAR_ID\":\"FF00FF00\",\"SH_ID\":\"ABCDEFGH\",\"SERVICE_ID\":\"18\",\"DEVICE_TYPE\":\"01\",\"LOCATION\":\"RTLAB502\",\"TIME\":\"2022-11-29 17:01:29\"},\"BODY\":{\"DATA\":{\"CMD\":\"ff\",\"ENV\":\""+file_content.hex()+"\"}}}"
                log_msg_mqtt = log_msg.split(",")
                # JSON formatting
                found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/ADL_DETECTOR"))]
                mqtt_msg_dict = {}
                mqtt_msg_dict.update(address=address)
                mqtt_msg_dict.update(location=found_location)
                mqtt_msg_dict.update(time=time_dt.strftime("%Y-%m-%d %H:%M:%S"))
                mqtt_msg_dict.update(press=log_msg_mqtt[0])
                mqtt_msg_dict.update(temp=log_msg_mqtt[1])
                mqtt_msg_dict.update(humid=log_msg_mqtt[2])
                mqtt_msg_dict.update(gas_raw=log_msg_mqtt[3])
                mqtt_msg_dict.update(iaq=log_msg_mqtt[4])
                mqtt_msg_dict.update(s_iaq=log_msg_mqtt[5])
                mqtt_msg_dict.update(eco2=log_msg_mqtt[6])
                mqtt_msg_dict.update(bvoc=log_msg_mqtt[7])
                mqtt_msg_dict.update(gas_percent=log_msg_mqtt[8])
                mqtt_msg_dict.update(rawdata=data.hex())

                LogProcess.queue.put(mqtt_msg_dict)

                # mqtt_msg_json = json.dumps(mqtt_msg_dict)
                # # print(mqtt_msg_json)

                # print("[MQTT] : " + mqtt_msg_json)
                # # print("[LOG] : " + time_dt.strftime("%X")+","+log_msg)
                # self.mqtt.publish("/CSOS/ADL/ENVDATA",mqtt_msg_json)
                
                # # packing data to integer.decimal (int).(int) format
                # msgq_payload_packing_format = "<"+"i"*18
                # msgq_payload_dec_resolution = 10000
                # msgq_payload_list = []
                # msgq_payload_list.append(float(log_msg_mqtt[0]))
                # msgq_payload_list.append(float(log_msg_mqtt[1]))
                # msgq_payload_list.append(float(log_msg_mqtt[2]))
                # msgq_payload_list.append(float(log_msg_mqtt[3]))
                # msgq_payload_list.append(float(log_msg_mqtt[4]))
                # msgq_payload_list.append(float(log_msg_mqtt[5]))
                # msgq_payload_list.append(float(log_msg_mqtt[6]))
                # msgq_payload_list.append(float(log_msg_mqtt[7]))
                # msgq_payload_list.append(float(log_msg_mqtt[8]))
                # env_msgq_payload_temp = struct.pack(msgq_payload_packing_format,
                #                                     int(msgq_payload_list[0]), int((msgq_payload_list[0] - int(msgq_payload_list[0]))*msgq_payload_dec_resolution),    #pressure
                #                                     int(msgq_payload_list[1]), int((msgq_payload_list[1] - int(msgq_payload_list[1]))*msgq_payload_dec_resolution),    #temperature
                #                                     int(msgq_payload_list[2]), int((msgq_payload_list[2] - int(msgq_payload_list[2]))*msgq_payload_dec_resolution),    #humidity
                #                                     int(msgq_payload_list[3]), int((msgq_payload_list[3] - int(msgq_payload_list[3]))*msgq_payload_dec_resolution),    #gas_adc_raw
                #                                     int(msgq_payload_list[4]), int((msgq_payload_list[4] - int(msgq_payload_list[4]))*msgq_payload_dec_resolution),    #IAQ
                #                                     int(msgq_payload_list[5]), int((msgq_payload_list[5] - int(msgq_payload_list[5]))*msgq_payload_dec_resolution),    #s_IAQ
                #                                     int(msgq_payload_list[6]), int((msgq_payload_list[6] - int(msgq_payload_list[6]))*msgq_payload_dec_resolution),    #eco2
                #                                     int(msgq_payload_list[7]), int((msgq_payload_list[7] - int(msgq_payload_list[7]))*msgq_payload_dec_resolution),    #bvoc
                #                                     int(msgq_payload_list[8]), int((msgq_payload_list[8] - int(msgq_payload_list[8]))*msgq_payload_dec_resolution))    #gas_percent
                # self.msgq.send(env_msgq_payload_temp, MSGQ_TYPE_ENV)
                f.write(time_dt.strftime("%Y-%m-%d %H:%M:%S")+","+file_msg+"\n")

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