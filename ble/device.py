# %%
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
import paho.mqtt.client as mqtt

import sound_service as snd
# import tensorflow_lite as tflite



SAMPLE_RATE = 16000
UNIT_WAV_SAMPLES = 16000

class Device:
    room = {}
    room["0001"] = "KITCHEN"
    room["0002"] = "LIVING"
    room["0003"] = "ROOM"
    room["0004"] = "TOILET"
    room["0005"] = "HOME_ENTRANCE"
    room["0006"] = "LIVING_ENTRANCE"
    room["0007"] = "KITCHEN_ENTRANCE"
    room["0008"] = "STAIR"

    room["ff01"] = "RTLAB501"
    room["ff02"] = "RTLAB502"
    room["ff03"] = "RTLAB503"
    room["ffff"] = "TEST"

    device = {}
    device["0001"] = "ADL_DETECTOR"
    device["0002"] = "THINGY53"
    device["0003"] = "ATT"

    data_type = {}
    data_type["0001"] = "RAW"
    data_type["0002"] = "GRIDEYE_ACTION"
    data_type["0003"] = "ENVIRONMENT"
    data_type["0004"] = "SOUND"
    data_type["0005"] = "AAT_ACTION"

    lookup = [room, device, data_type]

    def __init__(self, dev):
        self.dev = dev
        self.device_type = '' 
        self.device_name = ''
        self.services = []
        self.data_path = {}
        self.pcm_buffer = []

        self.env_interpreter = None
        self.speaker_interpreter = None
        
        self.pipe_ble, self.pipe_process = mp.Pipe()

    # tflite functions ------------------------------------------------------------
    def set_env_interpreter(self, model_path):
        self.env_interpreter = tflite.set_interpreter(model_path)

    def set_speaker_interpreter(self, model_path):
        self.speaker_interpreter = tflite.set_interpreter(model_path)

    # ble functions ------------------------------------------------------------
    def disconnected_callback(client):
        print(f'Device {client.address} disconnected, reason')
        print(client)

    def save_file_at_dir(dir_path, filename, file_content, mode='a'):
        with open(os.path.join(dir_path, filename), mode) as f:
            if len(file_content) == 1:
                grideye_msg = ""
                grideye_unpacked = struct.unpack("<B", file_content)
                grideye_msg = grideye_msg+str(grideye_unpacked)
                # f.write(datetime.now().strftime("%X")+","+str(grideye_msg)+"\n")
                grideye_msg = grideye_msg.replace("(", "").replace(")", "")
                grideye_msg = grideye_msg.replace(",,", ",")
                f.write(datetime.now().strftime("%X")+","+grideye_msg+"\n")

                mqtt_msg_dict = {}
            elif len(file_content) == 10:
                aat_msg = ""
                aat_unpacked = struct.unpack("<BBBBBBBBBB", file_content)
                aat_msg = aat_msg+str(aat_unpacked)
                # f.write(datetime.now().strftime("%X")+","+str(aat_msg)+"\n")
                aat_msg = aat_msg.replace("(", "").replace(")", "")
                aat_msg = aat_msg.replace(",,", ",")
                f.write(datetime.now().strftime("%X")+","+aat_msg+"\n")

                # found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/AAT"))]
                # mqtt_msg_dict = {}
                # mqtt_msg_dict.update(SH_ID=sh_id_str)
                # mqtt_msg_dict.update(location=found_location)
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



                # # mqtt_msg=press_i+press_d+temp_i+temp_d+humid_i+gas_raw_i+eco2_i+bvoc_i+red+green+blue+clear
                # # message="{\"HEADER\":{\"PAAR_ID\":\"FF00FF00\",\"SH_ID\":\"ABCDEFGH\",\"SERVICE_ID\":\"18\",\"DEVICE_TYPE\":\"01\",\"LOCATION\":\"RTLAB502\",\"TIME\":\"2022-11-29 17:01:29\"},\"BODY\":{\"DATA\":{\"CMD\":\"ff\",\"ENV\":\""+file_content.hex()+"\"}}}"
                # log_msg_mqtt = log_msg.split(",")
                # # JSON formatting
                # found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/ADL_DETECTOR"))]
                # mqtt_msg_dict = {}
                # mqtt_msg_dict.update(SH_ID=sh_id_str)
                # mqtt_msg_dict.update(location=found_location)
                # mqtt_msg_dict.update(time=datetime.now().strftime("%Y-%m-%d %X"))
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
                # print(mqtt_msg_json)

                # mqtt_msg = datetime.now().strftime("%X")+","+log_msg+file_content.hex()
                # print("[MQTT] : " + mqtt_msg_json)
                # # print("[LOG] : " + datetime.now().strftime("%X")+","+log_msg)
                # mqtt.publish("/CSOS/ADL/ENVDATA",mqtt_msg_json)
                f.write(datetime.now().strftime("%X")+","+file_msg+"\n")
                
    def process_data(self):
        while True:
            sender, data = self.pipe_process.recv()
            if len(data) < 37:
                self.save_file_at_dir(self.path[str(self.dev.address)+str(sender.handle)],str(datetime.now().strftime("%Y.%m.%d"))+".txt", data)
            else:
                pcm = snd.adpcm_decode(data)
                self.pcm_buffer.extend(pcm)

                if (len(self.pcm_buffer) >= (UNIT_WAV_SAMPLES*5)):
                    snd.save_wav(self.path[str(self.dev.address)+str(sender.handle)]+"/"+str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))+".wav",
                                self.pcm_buffer, SAMPLE_RATE)
                    self.pcm_buffer.clear()

                # if (len(pcm_buffer_inference[str(self.dev.address)+str(sender.handle)]) >= (UNIT_WAV_SAMPLES)):
                #     mfcc = snd.get_mfcc(pcm_buffer_inference[str(self.dev.address)+str(sender.handle)][:UNIT_WAV_SAMPLES],
                #                     sr=SAMPLE_RATE, n_mfcc=32, n_mels=64, n_fft=1000, n_hop=500)

                #     pcm_buffer_inference[str(self.dev.address)+str(sender.handle)].clear()

                #     result = tflite.inference(
                #         tflite_sound_interpreter[str(self.dev.address)+str(sender.handle)], mfcc)
                #     print(str(self.dev.address)+':')
                #     if np.max(result) < 0.8:
                #         print("Unknown sound")
                #     else:
                #         print(np.argmax(result))
                #         # print(np.max(result))

    def notify_callback(self, sender, data):
        self.pipe_ble.send([sender, data])

    async def ble_worker(self):
        while True:
            try:
                async with BleakClient(self.dev.address) as client:
                    client.set_disconnected_callback(self.disconnected_callback)
                    self.services = await client.get_services()
                    for service in self.services:
                        for characteristic in service.characteristics:
                            try:
                                path = os.getcwd()+"/data"

                                for i in range(3):
                                    if i == 2:
                                        self.path = os.path.join(self.path, self.dev.name.split("_")[1])
                                    if Device.lookup[i].get(characteristic.uuid.split("-")[i+1]) != None:
                                        path = os.path.join(path, Device.lookup[i].get(characteristic.uuid.split("-")[i+1]))
                                        # print(Device.lookup[i].get(characteristic.uuid.split("-")[i]))
                                        # if Device.lookup[i].get(characteristic.uuid.split("-")[i]) == "SOUND":
                                            # tflite_sound_interpreter[str(
                                            #     self.dev.address)+str(characteristic.handle)] = tflite.set_interpreter(sound_model_path)
                                    else:
                                        raise NotImplementedError
                                self.path[str(self.dev.address)+str(characteristic.handle)] = path
                                print(self.path[str(self.dev.address)+str(characteristic.handle)])
                                os.makedirs(path, exist_ok=True)
                                await client.start_notify(characteristic.uuid, partial(self.notify_callback, self.dev))
                            except:
                                pass

                    # task_ok[self.dev] = False
                    # while client.is_connected:
                    #     await asyncio.sleep(5.0)
            except Exception as e:
                pass
    
    async def ble_worker_start(self):
        worker = asyncio.create_task(self.ble_worker())
        await worker
