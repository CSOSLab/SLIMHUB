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
import sound_process as snd
import tensorflow_lite as tflite

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_UNIT_SAMPLES = 16000

class Device:
    # Class variables ------------------------------------------------------------
    connected_devices = {}

    lookup = {
        'room': {
            '0001': 'KITCHEN',
            '0002': 'LIVING',
            '0003': 'ROOM',
            '0004': 'TOILET',
            '0005': 'HOME_ENTRANCE',
            '0006': 'LIVING_ENTRANCE',
            '0007': 'KITCHEN_ENTRANCE',
            '0008': 'STAIR',
            'ff01': 'RTLAB501',
            'ff02': 'RTLAB502',
            'ff03': 'RTLAB503',
            'ffff': 'TEST'
        },
        'device_type': {
            '0001': 'ADL_DETECTOR',
            '0002': 'THINGY53',
            '0003': 'ATT'
        },
        'data_type': {
            '0001': 'RAW',
            '0002': 'GRIDEYE_ACTION',
            '0003': 'ENVIRONMENT',
            '0004': 'SOUND',
            '0005': 'AAT_ACTION'
        }
    }

    mqtt = None

    classlist = ['speech', 'microwave', 'vacuuming', 'tv', 'eating', 
                'drop', 'cooking', 'dish_clanging', 'peeing', 'chopping', 
                'water_flowing', 'toilet_flushing', 'walking']

    # Class functions ------------------------------------------------------------
    def __init__(self, dev):
        Device.connected_devices[dev.address] = self
        
        self.dev = dev

        self.device_name = dev.name
        self.device_address = dev.address
        self.device_type = '' 
        self.device_location = ''
        
        self.path = {}

        self.sound_sample_rate = DEFAULT_SAMPLE_RATE
        self.sound_unit_samples = DEFAULT_UNIT_SAMPLES
        self.sound_clip_length_sec = 30

        self.pcm_buffer_save = []
        self.pcm_buffer = []

        self.result_threshold = 0.8
        self.voting_buffer = []
        self.voting_buffer_len = 9
        self.result_buffer = [] 
        
        self.pipe_ble, self.pipe_process = mp.Pipe()
        self.pipe_ble_sound, self.pipe_process_sound = mp.Pipe()
        self.queue_log = mp.Queue()

        self.ble_client = None
        self.data_process = None

        self.data_process = mp.Process(target=self._process_data)
        self.sound_process = mp.Process(target=self._process_sound)
        # self.msg_process = mp.Process(target=self._process_msg)
    
    # def __del__(self):
    #     self.remove()

    def remove(self):
        Device.connected_devices.pop(self.device_address, None)
        try:
            self.data_process.terminate()
            self.sound_process.terminate()
            # self.msg_process.terminate()
            self.pipe_process.close()
            self.pipe_ble.close()
            self.pipe_process_sound.close()
            self.pipe_ble_sound.close()
            self.queue_log.close()
        except:
            pass
        finally:
            del self
        
    # TFLite functions ------------------------------------------------------------
    def set_env_sound_interpreter(self, model_path):
        self.env_interpreter = tflite.set_interpreter(model_path)

    def set_speaker_interpreter(self, model_path):
        self.speaker_interpreter = tflite.set_interpreter(model_path)

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
                grideye_msg = ""
                grideye_unpacked = struct.unpack("<B", file_content)
                grideye_msg = grideye_msg+str(grideye_unpacked)
                # f.write(datetime.now().strftime("%X")+","+str(grideye_msg)+"\n")
                grideye_msg = grideye_msg.replace("(", "").replace(")", "")
                grideye_msg = grideye_msg.replace(",,", ",")
                f.write(datetime.now().strftime("%X")+","+grideye_msg+"\n")
                found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/ADL_DETECTOR"))]
                mqtt_msg_dict = {}
                mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                # mqtt_msg_dict.update(location=self.deivce_location)
                mqtt_msg_dict.update(location=found_location)
                mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %X"))
                mqtt_msg_dict.update(grideye_raw=grideye_msg)
                mqtt_msg_json = json.dumps(mqtt_msg_dict)
                print(mqtt_msg_dict)
                self.mqtt.publish("/CSOS/ADL/ADLGRIDEYE",mqtt_msg_json)

                mqtt_msg_dict = {}
            elif len(file_content) == 10:
                aat_msg = ""
                aat_unpacked = struct.unpack("<BBBBBBBBBB", file_content)
                aat_msg = aat_msg+str(aat_unpacked)
                # f.write(datetime.now().strftime("%X")+","+str(aat_msg)+"\n")
                aat_msg = aat_msg.replace("(", "").replace(")", "")
                aat_msg = aat_msg.replace(",,", ",")
                f.write(datetime.now().strftime("%X")+","+aat_msg+"\n")

                found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/AAT"))]
                mqtt_msg_dict = {}
                mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                mqtt_msg_dict.update(location=found_location)
                mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %X"))
                # mqtt_msg_dict.update(aat=)
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
                mqtt_msg_dict = {}
                mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                mqtt_msg_dict.update(location=found_location)
                mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %X"))
                mqtt_msg_dict.update(press=log_msg_mqtt[0])
                mqtt_msg_dict.update(temp=log_msg_mqtt[1])
                mqtt_msg_dict.update(humid=log_msg_mqtt[2])
                mqtt_msg_dict.update(gas_raw=log_msg_mqtt[3])
                mqtt_msg_dict.update(iaq=log_msg_mqtt[4])
                mqtt_msg_dict.update(s_iaq=log_msg_mqtt[5])
                mqtt_msg_dict.update(eco2=log_msg_mqtt[6])
                mqtt_msg_dict.update(bvoc=log_msg_mqtt[7])
                mqtt_msg_dict.update(gas_percent=log_msg_mqtt[8])
                mqtt_msg_dict.update(rawdata=file_content.hex())

                mqtt_msg_json = json.dumps(mqtt_msg_dict)
                # print(mqtt_msg_json)

                mqtt_msg = datetime.now().strftime("%X")+","+log_msg+file_content.hex()
                print("[MQTT] : " + mqtt_msg_json)
                # print("[LOG] : " + datetime.now().strftime("%X")+","+log_msg)
                self.mqtt.publish("/CSOS/ADL/ENVDATA",mqtt_msg_json)
                f.write(datetime.now().strftime("%X")+","+file_msg+"\n")
    
    def _process_data(self):
        while True:
            sender, data = self.pipe_process.recv()

            if len(data) < 37:
                self._save_file_at_dir(self.path[str(sender.handle)],str(datetime.now().strftime("%Y.%m.%d"))+".txt", data)
                
    def _process_sound(self):
        window_hop = int((self.sound_unit_samples * self.sound_clip_length_sec)/2)

        while True:
            sender, data = self.pipe_process_sound.recv()

            wav_path = os.path.join(self.path[str(sender.handle)],"wavfiles",str(datetime.now().strftime("%Y.%m.%d")))
            
            os.makedirs(os.path.join(self.path[str(sender.handle)],"logs"), exist_ok=True)
            os.makedirs(os.path.join(self.path[str(sender.handle)],"raw"), exist_ok=True)

            f_logs = open(os.path.join(self.path[str(sender.handle)],"logs",str(datetime.now().strftime("%Y.%m.%d.%H"))+".txt"), 'a')
            f_raw = open(os.path.join(self.path[str(sender.handle)],"raw",str(datetime.now().strftime("%Y.%m.%d.%H"))+".txt"), 'a')

            # Mic stop trigger packet: save wav and clear buffer
            if data == b'\xff\xff\xff\xff':
                os.makedirs(wav_path, exist_ok=True)
                snd.save_wav(os.path.join(wav_path, str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))+".wav"), self.pcm_buffer_save, self.sound_sample_rate)
                self.pcm_buffer.clear()
                self.pcm_buffer_save.clear()
                self.voting_buffer.clear()
                continue
            
            pcm = snd.adpcm_decode(data)

            self.pcm_buffer.extend(pcm)
            self.pcm_buffer_save.extend(pcm)
            
            # Save wav files every 'sound_clip_length_sec' sec
            if len(self.pcm_buffer_save) >= (self.sound_sample_rate * self.sound_clip_length_sec):
                os.makedirs(wav_path, exist_ok=True)
                snd.save_wav(os.path.join(wav_path, str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))+".wav"), self.pcm_buffer_save, self.sound_sample_rate)
                self.pcm_buffer_save.clear()

            # Inference every 'window_hop' sec
            if (len(self.pcm_buffer) >= (self.sound_unit_samples)):
                # Preprocess and inference
                mfcc = snd.get_mfcc(self.pcm_buffer[:self.sound_unit_samples], sr=self.sound_sample_rate, n_mfcc=32, n_mels=64, n_fft=1000, n_hop=500)

                result = tflite.inference(self.env_interpreter, mfcc)

                # Save raw inference result
                time = str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))
                f_raw.write(time+','+','.join(result.astype(str))+'\n')

                # Postprocessing
                self.voting_buffer.append(result)
                if len(self.voting_buffer) == self.voting_buffer_len:
                    # Todo: Postprocessing
                    buf = np.array(self.voting_buffer).swapaxes(0, 1)
                    counts = np.sum(buf > self.result_threshold, axis=1)
                    idxs = np.where(counts != 0)[0]
                    for idx in idxs:
                        mean = np.mean(buf[idx][buf[idx] > self.result_threshold])
                        f_logs.write(time+','+Device.classlist[idx]+','+str(counts[idx])+','+'%.2f'%mean+'\n')
                        
                        # Send MQTT packet
                        mqtt_msg_dict = {}
                        mqtt_msg_dict.update(SH_ID=self.mqtt.sh_id)
                        mqtt_msg_dict.update(location=self.device_location)
                        mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %X"))
                        mqtt_msg_dict.update(inference_index=int(idx))
                        mqtt_msg_dict.update(inference_result=Device.classlist[idx])
                        mqtt_msg_dict.update(counts=int(counts[idx]))
                        mqtt_msg_dict.update(mean='%.2f'%mean)
                        mqtt_msg_json = json.dumps(mqtt_msg_dict)
                        print(mqtt_msg_json)
                        self.mqtt.publish("/CSOS/ADL/ADLSOUND",mqtt_msg_json)
                        
                        # Print inference result
                        print(Device.classlist[idx], counts[idx], '%.2f'%mean)

                    self.voting_buffer = self.voting_buffer[5:]

                self.pcm_buffer = self.pcm_buffer[window_hop:]

            f_logs.close()
            f_raw.close()

    def _process_msg(self):
        while True:
            # Todo: Save log and send mqtt
            # Add timestamp here: To arrange different types of messages

            type, msg = self.queue_log.get()

            if type == 'SOUND':
                continue
            elif type == 'ENV':
                continue
            elif type == 'GRIDEYE':
                continue
            elif type == 'AAT':
                continue
            else:
                continue
    
    def _process_start_all(self):
        self.data_process.start()
        self.sound_process.start()
        # self.msg_process.start()
    
    # BLE functions ------------------------------------------------------------
    def _data_notify_callback(self, dev, sender, data):
        if self.data_process.is_alive():
            self.pipe_ble.send([sender, data])
    
    def _sound_notify_callback(self, dev, sender, data):
        if self.sound_process.is_alive():
            self.pipe_ble_sound.send([sender, data])

    async def _ble_worker(self, disconnected_callback=None):
        self.ble_client = BleakClient(self.device_address, disconnected_callback=disconnected_callback)

        try:
            await self.ble_client.connect()

            for service in self.ble_client.services:
                for characteristic in service.characteristics:
                    try:
                        path = os.getcwd()+"/data"

                        uuid_split = characteristic.uuid.split("-")

                        self.device_location = Device.lookup['room'].get(uuid_split[1])
                        self.device_type = Device.lookup['device_type'].get(uuid_split[2])
                        current_data_type = Device.lookup['data_type'].get(uuid_split[3])

                        path = os.path.join(path, self.device_location, self.device_type, self.device_address, current_data_type)
                        
                        self.path[str(characteristic.handle)] = path
                        print(self.path[str(characteristic.handle)])
                        os.makedirs(path, exist_ok=True)

                        # Check data type
                        if current_data_type == "SOUND":
                            await self.ble_client.start_notify(characteristic.uuid, partial(self._sound_notify_callback, self.dev))
                        else:
                            await self.ble_client.start_notify(characteristic.uuid, partial(self._data_notify_callback, self.dev))

                    except Exception as e:
                        print(e)
                        pass          

        except Exception as e:
            print(e)
            pass

        finally:
            if self.ble_client.is_connected:
                self._process_start_all()
            else:
                self.remove()
    
    async def ble_client_start(self, disconnected_callback=None):
        await self._ble_worker(disconnected_callback)