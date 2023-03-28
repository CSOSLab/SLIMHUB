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

lookup=[]
room={}
room["0001"]="KITCHEN"
room["0002"]="LIVING"
room["0003"]="ROOM"
room["0004"]="TOILET"
room["0005"]="HOME_ENTRANCE"
room["0006"]="LIVING_ENTRANCE"
room["0007"]="KITCHEN_ENTRANCE"
room["0008"]="STAIR"


device={}
device["0001"]="ADL_DETECTOR"
device["0002"]="THINGY53"
device["0003"]="ATT"

data_type={}
data_type["0001"]="RAW"
data_type["0002"]="GRIDEYE_ACTION"
data_type["0003"]="ENVIRONMENT"
data_type["0004"]="SOUND"
data_type["0005"]="AAT_ACTION"
path={}
lookup.append(path)
lookup.append(room)
lookup.append(device)
lookup.append(data_type)

task_ok={}

pcm_buffer = {}
#pcm_buffer = []
# /** Intel ADPCM step variation table */
INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8,]
global sh_id_str
sh_id_str = "HMK0H001"

# /** ADPCM step size table */
STEP_SIZE_TABLE = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209,
                   230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
                   5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]
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

def adpcm_decode(adpcm) :
    # // Allocate output buffer
    pcm = []

    # // The first 2 bytes of ADPCM frame are the predicted value
    valuePredicted = int.from_bytes(adpcm[:2], byteorder='big', signed=True)
	# // The 3rd byte is the index value
    index = int(adpcm[2])
    data = adpcm[3:]

    if (index < 0) :
        index = 0
    if (index > 88) :
        index = 88

    for value in data :
        deltas = [(value >> 4) & 0x0f, value & 0x0f]
        for delta in deltas :
            # Update step value
            step = STEP_SIZE_TABLE[index]
            
            # /* Step 2 - Find new index value (for later) */
            index = index + INDEX_TABLE[delta]
            if index < 0 :
                index = 0
            if index > 88 :
                index = 88

            # /* Step 3 - Separate sign and magnitude */
            sign = delta & 8
            delta = delta & 7

            # /* Step 4 - Compute difference and new predicted value */
            diff = (step >> 3)
            if (delta & 4) > 0 :
                diff += step
            if (delta & 2) > 0 :
                diff += step >> 1
            if (delta & 1) > 0 :
                diff += step >> 2

            if sign > 0 :
                valuePredicted = valuePredicted-diff
            else :
                valuePredicted = valuePredicted+diff

            # /* Step 5 - clamp output value */
            if valuePredicted > 32767 :
                valuePredicted = 32767
            elif valuePredicted < -32768 :
                valuePredicted = -32768

            valuePredicted = np.float32(valuePredicted/32768)
            # /* Step 7 - Output value */
            pcm.append(valuePredicted)

    return pcm

async def scan():
    target_devices = []
    devices = await BleakScanner.discover()
    #print(devices)
    # print(devices)
    for dev in devices:
        if dev.name.split("_")[0] == 'ADL':
            target_devices.append(dev)
    return target_devices


def notify_callback(dev, sender, data):
    if len(data) < 37:
        save_file_at_dir(lookup[0][str(dev.address)+str(sender.handle)],str(datetime.now().strftime("%Y.%m.%d"))+".txt",data)
    else:
        pcm = adpcm_decode(data)
        pcm_buffer[str(dev.address)+str(sender.handle)].extend(pcm)
        if(len(pcm_buffer[str(dev.address)+str(sender.handle)]) >= 160000) :
            sf.write(lookup[0][str(dev.address)+str(sender.handle)]+"/"+str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))+".wav", pcm_buffer[str(dev.address)+str(sender.handle)], 16000, 'PCM_16')
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
                            path=os.getcwd()+"/data"
                            for i in range(1,4):
                                if i==3:
                                    path=os.path.join(path,dev.name.split("_")[1])
                                if lookup[i].get(characteristic.uuid.split("-")[i]) !=None:
                                    path=os.path.join(path,lookup[i].get(characteristic.uuid.split("-")[i]))
                                    if lookup[i].get(characteristic.uuid.split("-")[i]) == "SOUND":
                                        pcm_buffer[str(dev.address)+str(characteristic.handle)]=[]
                                else:
                                    raise NotImplementedError
                            lookup[0][str(dev.address)+str(characteristic.handle)]=path
                            print(lookup[0][str(dev.address)+str(characteristic.handle)])
                            os.makedirs(path, exist_ok=True)
                            await client.start_notify(characteristic.uuid, partial(notify_callback,dev))
                        except:
                            pass                

                task_ok[dev]=False
                while client.is_connected :
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
                    task_ok[dev]=True
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
            grideye_unpacked = struct.unpack("<B",file_content)
            grideye_msg = grideye_msg+str(grideye_unpacked)
            # f.write(datetime.now().strftime("%X")+","+str(grideye_msg)+"\n")
            grideye_msg=grideye_msg.replace("(","").replace(")","")
            grideye_msg=grideye_msg.replace(",,",",")
            f.write(datetime.now().strftime("%X")+","+grideye_msg+"\n")
            
            mqtt_msg_dict = {}
            
        elif len(file_content) == 10:
            aat_msg = ""
            aat_unpacked = struct.unpack("<BBBBBBBBBB",file_content)
            aat_msg = aat_msg+str(aat_unpacked)
            # f.write(datetime.now().strftime("%X")+","+str(aat_msg)+"\n")
            aat_msg=aat_msg.replace("(","").replace(")","")
            aat_msg=aat_msg.replace(",,",",")
            f.write(datetime.now().strftime("%X")+","+aat_msg+"\n")
            
            found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/AAT"))]
            mqtt_msg_dict = {}
            mqtt_msg_dict.update(SH_ID=sh_id_str)
            mqtt_msg_dict.update(location=found_location)
            # mqtt_msg_dict.update(aat=)
            
        else:
            if os.path.getsize(os.path.join(dir_path, filename)) == 0:
                f.write("time,press,temp,humid,gas_raw,iaq,s_iaq,eco2,bvoc,gas_percent,clear\n")
            # data_str=str(file_content[0])+"."+str(file_content[1])+","+\
            # str(file_content[2])+"."+str(file_content[3])+","+\
            # str(file_content[4])+"."+str(file_content[5])+","+\
            # str(file_content[6])+"."+str(file_content[7])
            file_msg=""
            log_msg=""
            for i in range(9):
                temp_msg = struct.unpack('<f',file_content[4*i:4*(i+1)])
                file_msg=file_msg+str(temp_msg)+","
                temp_msg = str(temp_msg).replace("(","").replace(",)","")
                log_msg=log_msg+format(float(temp_msg), '.3f')+","
            file_msg=file_msg.replace("(","").replace(")","")
            file_msg=file_msg.replace(",,",",")
            log_msg=log_msg.replace("(","").replace(")","")
            log_msg=log_msg.replace(",,",",")

            #mqtt_msg=press_i+press_d+temp_i+temp_d+humid_i+gas_raw_i+eco2_i+bvoc_i+red+green+blue+clear
            # message="{\"HEADER\":{\"PAAR_ID\":\"FF00FF00\",\"SH_ID\":\"ABCDEFGH\",\"SERVICE_ID\":\"18\",\"DEVICE_TYPE\":\"01\",\"LOCATION\":\"RTLAB502\",\"TIME\":\"2022-11-29 17:01:29\"},\"BODY\":{\"DATA\":{\"CMD\":\"ff\",\"ENV\":\""+file_content.hex()+"\"}}}"
            log_msg_mqtt = log_msg.split(",")
            # JSON formatting
            found_location = dir_path[(dir_path.find("data/")+5):(dir_path.find("/ADL_DETECTOR"))]
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
            print("[MQTT] : " + mqtt_msg_json)
            # print("[LOG] : " + datetime.now().strftime("%X")+","+log_msg)
            mqtt.publish("/CSOS/ADL/ENVDATA",mqtt_msg_json)
            f.write(datetime.now().strftime("%X")+","+file_msg+"\n")
            

if __name__ == "__main__":
    print("Mqtt On")
    mqtt=Mqtt("155.230.186.52",1883,"csosMember","csos!1234")
    mqtt.connect()
    print("Run Main")
    asyncio.run(main())
