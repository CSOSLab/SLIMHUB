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

import mqtt
import msgq
import sound_process as snd
import tensorflow_lite as tflite
import sysv_ipc

class Process:
    queue = None
    process = None

    def get_queue(self):
        return self.queue
    
    def start(self):
        self.process.start()
    
class SoundProcess(Process):
    DEFAULT_SAMPLE_RATE = 16000
    DEFAULT_UNIT_SAMPLES = 16384

    classlist = ['speech', 'microwave', 'vacuuming', 'tv', 'eating', 'drop', 'smoke_extractor',
                 'cooking', 'dish_clanging', 'peeing', 'chopping', 'water_flowing',
                 'toilet_flushing', 'walking', 'brushing_teeth']

    data_collection_mode = False

    class Buffer:
        def __init__(self):
            self.pcm_buffer = []
            self.mfcc_buffer = []
            self.voting_buffer = []
            self.result_buffer = []

    def __init__(self):
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)

        self.sound_sample_rate = self.DEFAULT_SAMPLE_RATE
        self.sound_unit_samples = self.DEFAULT_UNIT_SAMPLES
        self.sound_clip_length_sec = 30

        self.result_threshold = 0.6
        self.voting_buffer_len = 7

        self.buffer = {}
    
    # TFLite functions ------------------------------------------------------------
    def set_env_sound_interpreter(self, model_path):
        self.env_interpreter = tflite.set_interpreter(model_path)
    
    def _run(self):
        window_hop = int((self.sound_unit_samples * self.sound_clip_length_sec)/2)

        while True:
            address, path, data = self.queue.get()

            if address not in self.buffer:
                self.buffer[address] = self.Buffer()
            
            current_buffer = self.buffer[address]

            wav_path = os.path.join(path,"wavfiles",str(datetime.now().strftime("%Y-%m-%d")))
            
            os.makedirs(os.path.join(path,"logs"), exist_ok=True)
            os.makedirs(os.path.join(path,"raw"), exist_ok=True)

            f_logs = open(os.path.join(path,"logs",str(datetime.now().strftime("%Y-%m-%d_%H"))+".txt"), 'a')
            f_raw = open(os.path.join(path,"raw",str(datetime.now().strftime("%Y-%m-%d_%H"))+".txt"), 'a')

            # Mic stop trigger packet: save wav and clear buffer
            if data == b'\xff\xff\xff\xff':
                os.makedirs(wav_path, exist_ok=True)
                snd.save_wav(os.path.join(wav_path, str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))+".wav"), current_buffer.pcm_buffer, self.sound_sample_rate)
                current_buffer.pcm_buffer.clear()
                current_buffer.voting_buffer.clear()
                continue
            
            if self.data_collection_mode:
                pcm = snd.adpcm_decode(data)

                current_buffer.pcm_buffer.extend(pcm)
                
                # Save wav files every 'sound_clip_length_sec' sec
                if len(current_buffer.pcm_buffer) >= (self.sound_sample_rate * self.sound_clip_length_sec):
                    os.makedirs(wav_path, exist_ok=True)
                    snd.save_wav(os.path.join(wav_path, str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))+".wav"), current_buffer.pcm_buffer, self.sound_sample_rate)
                    current_buffer.pcm_buffer.clear()

                # Inference every 'window_hop' sec
                if (len(current_buffer.pcm_buffer) >= (self.sound_unit_samples)):
                    # Preprocess and inference
                    mfcc = snd.get_mfcc(current_buffer.pcm_buffer[:self.sound_unit_samples], sr=self.sound_sample_rate, n_mfcc=32, n_mels=64, n_fft=1000, n_hop=500)

                    result = tflite.inference(self.env_interpreter, mfcc)

                    # Save raw inference result
                    time = str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    f_raw.write(time+','+','.join(result.astype(str))+'\n')

                    # Postprocessing
                    current_buffer.voting_buffer.append(result)
                    if len(current_buffer.voting_buffer) == self.voting_buffer_len:
                        # Todo: Postprocessing
                        buf = np.array(current_buffer.voting_buffer).swapaxes(0, 1)
                        counts = np.sum(buf > self.result_threshold, axis=1)
                        idxs = np.where(counts != 0)[0]
                        for idx in idxs:
                            mean = np.mean(buf[idx][buf[idx] > self.result_threshold])
                            f_logs.write(time+','+self.classlist[idx]+','+str(counts[idx])+','+'%.2f'%mean+'\n')
                            
                            # # Send MQTT packet
                            # mqtt_msg_dict = {}
                            # mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                            # mqtt_msg_dict.update(location=self.device_location)
                            # mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            # mqtt_msg_dict.update(inference_index=int(idx))
                            # mqtt_msg_dict.update(inference_result=self.classlist[idx])
                            # mqtt_msg_dict.update(counts=int(counts[idx]))
                            # mqtt_msg_dict.update(mean='%.2f'%mean)

                            # mqtt_msg_json = json.dumps(mqtt_msg_dict)
                            # self.mqtt.publish("/CSOS/ADL/ADL_SOUND",mqtt_msg_json)
                            
                            # # packing data into string format
                            # msgq_payload_sound_str = ""
                            # # msgq_payload_sound_str = msgq_payload_sound_str+str(idx)+str(Device.classlist[idx])+str(counts[idx])+str('%.2f'%mean)
                            # msgq_payload_sound_str = msgq_payload_sound_str+"SJK,"+str(self.device_location)+","+str(self.classlist[idx])+","+str(idx)+","+str('%.2f'%mean)+",,,,,,,"+"\n"
                            # self.msgq.send(msgq_payload_sound_str, MSGQ_TYPE_SOUND)
                            
                            # Print inference result
                            print(self.classlist[idx], counts[idx], '%.2f'%mean)

                        current_buffer.voting_buffer = current_buffer.voting_buffer[5:]

                    current_buffer.pcm_buffer = current_buffer.pcm_buffer[window_hop:]
            else:
                current_buffer.mfcc_buffer.append([struct.unpack('<f', data[i:i+4])[0] for i in range(0, len(data), 4)])
                
                if len(current_buffer.mfcc_buffer) == 32:
                    result = tflite.inference(self.env_interpreter, np.array(current_buffer.mfcc_buffer, dtype='float32').T[..., np.newaxis])

                    # Save raw inference result
                    time = str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    f_raw.write(time+','+','.join(result.astype(str))+'\n')

                    # Postprocessing
                    current_buffer.voting_buffer.append(result)
                    if len(current_buffer.voting_buffer) == self.voting_buffer_len:
                        # Todo: Postprocessing
                        buf = np.array(current_buffer.voting_buffer).swapaxes(0, 1)
                        counts = np.sum(buf > self.result_threshold, axis=1)
                        idxs = np.where(counts != 0)[0]
                        for idx in idxs:
                            mean = np.mean(buf[idx][buf[idx] > self.result_threshold])
                            f_logs.write(time+','+self.classlist[idx]+','+str(counts[idx])+','+'%.2f'%mean+'\n')
                            
                            # # Send MQTT packet
                            # mqtt_msg_dict = {}
                            # mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                            # mqtt_msg_dict.update(location=self.device_location)
                            # mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            # mqtt_msg_dict.update(inference_index=int(idx))
                            # mqtt_msg_dict.update(inference_result=self.classlist[idx])
                            # mqtt_msg_dict.update(counts=int(counts[idx]))
                            # mqtt_msg_dict.update(mean='%.2f'%mean)

                            # mqtt_msg_json = json.dumps(mqtt_msg_dict)
                            # self.mqtt.publish("/CSOS/ADL/ADL_SOUND",mqtt_msg_json)
                            
                            # # packing data into string format
                            # msgq_payload_sound_str = ""
                            # # msgq_payload_sound_str = msgq_payload_sound_str+str(idx)+str(Device.classlist[idx])+str(counts[idx])+str('%.2f'%mean)
                            # msgq_payload_sound_str = msgq_payload_sound_str+"SJK,"+str(self.device_location)+","+str(self.classlist[idx])+","+str(idx)+","+str('%.2f'%mean)+",,,,,,,"+"\n"
                            # self.msgq.send(msgq_payload_sound_str, MSGQ_TYPE_SOUND)
                            
                            # Print inference result
                            print(self.classlist[idx], counts[idx], '%.2f'%mean)

                        current_buffer.voting_buffer = current_buffer.voting_buffer[5:]
                        
                    current_buffer.mfcc_buffer = current_buffer.mfcc_buffer[16:]
            
            f_logs.close()
            f_raw.close()

class DataProcess(Process):
    def __init__(self):
        self.queue = mp.Queue()
        self.process = mp.Process(target=self._run)
    # Process functions ------------------------------------------------------------
    def _save_file_at_dir(self, dir_path, filename, file_content, mode='a'):
        def swapEndianness(hexstring):
            ba = bytearray.fromhex(hexstring)
            ba.reverse()
            return ba.hex()
        
        # def mqtt_data(f_data):
        #     f_data_i=int(f_data)
        #     f_data_d=int((f_data-int(f_data))*100000)
        #     return str("%04x"%f_data_i), str("%04x"%f_data_d)
        
        with open(os.path.join(dir_path, filename), mode) as f:
            if len(file_content) == 1:
                if os.path.getsize(os.path.join(dir_path, filename)) == 0:
                    f.write("time,action\n")
                grideye_msg = ""
                grideye_unpacked = struct.unpack("<B", file_content)
                grideye_msg = grideye_msg+str(grideye_unpacked)
                # f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+","+str(grideye_msg)+"\n")
                grideye_msg = grideye_msg.replace("(", "").replace(")", "")
                grideye_msg = grideye_msg.replace(",,", ",")
                f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+","+grideye_msg+"\n")
                # mqtt_msg_dict = {}
                # mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                # mqtt_msg_dict.update(location=self.device_location)
                # mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                # mqtt_msg_dict.update(grideye_raw=grideye_msg)
                # mqtt_msg_json = json.dumps(mqtt_msg_dict)
                # self.mqtt.publish("/CSOS/ADL/ADLDATA",mqtt_msg_json)
                
                # # packing data into Device's Signal
                # msgq_payload_device_signal = ""
                # # msgq_payload_device_signal = msgq_payload_device_signal+str(grideye_msg)
                # msgq_payload_device_signal = msgq_payload_device_signal+"SJK,"+str(self.device_location)+","+str(grideye_msg[:2])+",,,,,,,,"+"\n"
                # self.msgq.send(msgq_payload_device_signal, MSGQ_TYPE_DEVICE)

                # mqtt_msg_dict = {}
            elif len(file_content) == 10:
                aat_msg = ""
                aat_unpacked = struct.unpack("<BBBBBBBBBB", file_content)
                aat_msg = aat_msg+str(aat_unpacked)
                # f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+","+str(aat_msg)+"\n")
                aat_msg = aat_msg.replace("(", "").replace(")", "")
                aat_msg = aat_msg.replace(",,", ",")
                f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+","+aat_msg+"\n")

                found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/AAT"))]
                # mqtt_msg_dict = {}
                # mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                # mqtt_msg_dict.update(location=found_location)
                # mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                # # mqtt_msg_dict.update(aat=)
            else:
                if os.path.getsize(os.path.join(dir_path, filename)) == 0:
                    f.write("time,press,temp,humid,gas_raw,iaq,s_iaq,eco2,bvoc,gas_percent,clear\n")
                # data_str=str(file_content[0])+"."+str(file_content[1])+","+\
                # str(file_content[2])+"."+str(file_content[3])+","+\
                # str(file_content[4])+"."+str(file_content[5])+","+\
                # str(file_content[6])+"."+str(file_content[7])
                file_msg = ""
                log_msg = ""
                for i in range(9):
                    temp_msg = struct.unpack('<f', file_content[4*i:4*(i+1)])
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
                # mqtt_msg_dict = {}
                # mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                # mqtt_msg_dict.update(location=found_location)
                # mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                # mqtt_msg_dict.update(press=log_msg_mqtt[0])
                # mqtt_msg_dict.update(temp=log_msg_mqtt[1])
                # mqtt_msg_dict.update(humid=log_msg_mqtt[2])
                # mqtt_msg_dict.update(gas_raw=log_msg_mqtt[3])
                # mqtt_msg_dict.update(iaq=log_msg_mqtt[4])
                # mqtt_msg_dict.update(s_iaq=log_msg_mqtt[5])
                # mqtt_msg_dict.update(eco2=log_msg_mqtt[6])
                # mqtt_msg_dict.update(bvoc=log_msg_mqtt[7])
                # mqtt_msg_dict.update(gas_percent=log_msg_mqtt[8])
                # mqtt_msg_dict.update(rawdata=file_content.hex())

                # mqtt_msg_json = json.dumps(mqtt_msg_dict)
                # # print(mqtt_msg_json)

                # print("[MQTT] : " + mqtt_msg_json)
                # # print("[LOG] : " + datetime.now().strftime("%X")+","+log_msg)
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
                f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+","+file_msg+"\n")
                print(file_msg)
    
    def _run(self):
        while True:
            address, path, data = self.queue.get()

            if len(data) < 37:
                self._save_file_at_dir(path, str(datetime.now().strftime("%Y-%m-%d"))+".txt", data)

class LogProcess(Process):
    MSGQ_TYPE_DEVICE = 1
    MSGQ_TYPE_ENV = 2
    MSGQ_TYPE_SOUND = 3
    
