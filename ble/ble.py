import asyncio
import os
from bleak import *
from datetime import datetime
import soundfile as sf
from functools import partial
import numpy as np
import time
import struct
import json
import paho.mqtt.client as mqtt

from sound_service import *

lookup = []
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
data_type["0002"] = "ACTION"
data_type["0003"] = "ENVIRONMENT"
data_type["0004"] = "SOUND"

path = {}

lookup.append(path)
lookup.append(room)
lookup.append(device)
lookup.append(data_type)

task_ok = {}

# Sound service variables ---------------------------------------------------------------------
pcm_buffer = {}
# pcm_buffer = []
SAMPLE_RATE = 16000
UNIT_WAV_SAMPLES = 16384

class Mqtt():
    def __init__(self, ip,port,id,passwd):
        self.ip = ip
        self.port = port
        self.id=id
        self.passwd=passwd
        self.client = mqtt.Client("Foot_Pressure")

    def connect(self):
        self.client.username_pw_set(username=self.id,password=self.passwd)
        self.client.connect(self.ip, self.port)

    def publish(self,topic,message):
        self.client.publish(topic,message)

    def disconnect(self):
        self.client.disconnect()

async def scan():
    target_devices = []
    devices = await BleakScanner.discover()
    # print(devices)
    # print(devices)
    for dev in devices:
        if dev.name.split("_")[0] == 'ADL':
            target_devices.append(dev)
    return target_devices


def notify_callback(dev, sender, data):
    if len(data) < 37:
        save_file_at_dir(lookup[0][str(dev.address)+str(sender.handle)],
                         str(datetime.now().strftime("%Y.%m.%d"))+".txt", data)
    else:
        pcm = adpcm_decode(data)
        pcm_buffer[str(dev.address)+str(sender.handle)].extend(pcm)
        if (len(pcm_buffer[str(dev.address)+str(sender.handle)]) >= (UNIT_WAV_SAMPLES*10)):
            sf.write(lookup[0][str(dev.address)+str(sender.handle)]+"/"+str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))+".wav",
                     pcm_buffer[str(dev.address)+str(sender.handle)], SAMPLE_RATE, 'PCM_16')
            pcm_buffer[str(dev.address)+str(sender.handle)].clear()


def disconnected_callback(client):
    print(f'Device {client.address} disconnected, reason')
    print(client)


async def work(dev):
    while True:
        try:
            async with BleakClient(dev.address) as client:
                client.set_disconnected_callback(disconnected_callback)
                services = await client.get_services()
                for service in services:
                    for characteristic in service.characteristics:
                        try:
                            path = os.getcwd()+"/data"
                            for i in range(1, 4):
                                if i == 3:
                                    path = os.path.join(
                                        path, dev.name.split("_")[1])
                                if lookup[i].get(characteristic.uuid.split("-")[i]) != None:
                                    path = os.path.join(path, lookup[i].get(
                                        characteristic.uuid.split("-")[i]))
                                    if lookup[i].get(characteristic.uuid.split("-")[i]) == "SOUND":
                                        pcm_buffer[str(
                                            dev.address)+str(characteristic.handle)] = []
                                else:
                                    raise NotImplementedError
                            lookup[0][str(dev.address) +
                                      str(characteristic.handle)] = path
                            print(lookup[0][str(dev.address) +
                                  str(characteristic.handle)])
                            os.makedirs(path, exist_ok=True)
                            await client.start_notify(characteristic.uuid, partial(notify_callback, dev))
                        except:
                            pass

                task_ok[dev] = False
                while client.is_connected:
                    await asyncio.sleep(5.0)
        except Exception as e:
            pass


task_list = []


async def main():
    while True:
        try:
            target_devices = await scan()
            for dev in target_devices:
                if str(dev) not in task_list:
                    print(dev, "find")
                    work_task = asyncio.create_task(work(dev))
                    task_ok[dev] = True
                    print("sleep on")
                    while task_ok[dev]:
                        await asyncio.sleep(1.0)
                    print("sleep off")
                    task_list.append(str(dev))
        except:
            pass
        await asyncio.sleep(10.0)
# def mqtt_data(f_data):
#     f_data_i=int(f_data)
#     f_data_d=int((f_data-int(f_data))*100000)
#     return str("%04x"%f_data_i), str("%04x"%f_data_d)


def swapEndianness(hexstring):
    ba = bytearray.fromhex(hexstring)
    ba.reverse()
    return ba.hex()


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
        elif len(file_content) == 10:
            aat_msg = ""
            aat_unpacked = struct.unpack("<BBBBBBBBBB", file_content)
            aat_msg = aat_msg+str(aat_unpacked)
            # f.write(datetime.now().strftime("%X")+","+str(aat_msg)+"\n")
            aat_msg = aat_msg.replace("(", "").replace(")", "")
            aat_msg = aat_msg.replace(",,", ",")
            f.write(datetime.now().strftime("%X")+","+aat_msg+"\n")
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

            # press_i,press_d=mqtt_data(file_content[0])
            # temp_i,temp_d=mqtt_data(file_content[1])
            # humid_i,humid_d=mqtt_data(file_content[2])
            # gas_raw_i,gas_raw_d=mqtt_data(file_content[3])
            # iaq_i,iaq_d=mqtt_data(file_content[4])
            # s_iaq_i,s_iaq_d=mqtt_data(file_content[5])
            # eco2_i,eco2_d=mqtt_data(file_content[6])
            # bvoc_i,bvoc_d=mqtt_data(file_content[7])
            # gas_percent_i,gas_percent_d=mqtt_data(file_content[8])
            # print(press_i,press_d,file_content[0])
            # print(temp_i,temp_d,file_content[1])
            # print(humid_i,humid_d,file_content[2])
            # print(gas_raw_i,gas_raw_d,file_content[3])
            # print(iaq_i,iaq_d,file_content[4])
            # print(s_iaq_i,s_iaq_d,file_content[5])
            # print(eco2_i,eco2_d,file_content[6])
            # print(bvoc_i,bvoc_d,file_content[7])
            # print(gas_percent_i,gas_percent_d,file_content[8])
            # print("++++++++++++++++++++++++")
            # red=str("%04x"%00)
            # green=str("%04x"%00)
            # blue=str("%04x"%00)
            # clear=str("%04x"%00)

            # mqtt_msg=press_i+press_d+temp_i+temp_d+humid_i+gas_raw_i+eco2_i+bvoc_i+red+green+blue+clear
            # message="{\"HEADER\":{\"PAAR_ID\":\"FF00FF00\",\"SH_ID\":\"ABCDEFGH\",\"SERVICE_ID\":\"18\",\"DEVICE_TYPE\":\"01\",\"LOCATION\":\"RTLAB502\",\"TIME\":\"2022-11-29 17:01:29\"},\"BODY\":{\"DATA\":{\"CMD\":\"ff\",\"ENV\":\""+file_content.hex()+"\"}}}"
            log_msg_mqtt = log_msg.split(",")
            # JSON formatting
            global sh_id_str
            sh_id_str = "HMK0H001"
            found_location = dir_path[(dir_path.find(
                "data/")+5):(dir_path.find("/ADL_DETECTOR"))]
            mqtt_msg_dict = {}
            mqtt_msg_dict.update(SH_ID=sh_id_str)
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
            print(mqtt_msg_json)

            mqtt_msg = datetime.now().strftime("%X")+","+log_msg+file_content.hex()
            # print("[MQTT] : " + mqtt_msg)
            # print("[LOG] : " + datetime.now().strftime("%X")+","+log_msg)
            # mqtt.publish("CSOS/AB001309/010000D1/SMARTHUB",message)
            f.write(datetime.now().strftime("%X")+","+file_msg+"\n")


if __name__ == "__main__":
    # print("Mqtt On")
    # mqtt=Mqtt("155.230.186.105",1883,"rtlab_SUB","RTLab123!")
    # mqtt.connect()
    print("Run Main")
    asyncio.run(main())
