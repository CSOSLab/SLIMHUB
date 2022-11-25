import asyncio
import os
from bleak import *
from datetime import datetime
import soundfile as sf
from functools import partial
import numpy as np
import time

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
data_type["0002"]="ACTION"
data_type["0003"]="ENVIRONMENT"
data_type["0004"]="SOUND"
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

# /** ADPCM step size table */
STEP_SIZE_TABLE = [7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209,
                   230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358,
                   5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767]

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


def notify_callback(dev,sender, data):
    # print(dev)
   

#    if int((datetime.utcnow()-datetime(1970, 1, 1)).total_seconds())%60==0:
#        print(lookup[0][str(dev.address)+str(sender.handle)],datetime.utcnow())
        
    if len(data) == 32:
        tmp_data=[]
        for i in range(8):
            tmp_data.append(int.from_bytes(data[4*i:4*(i+1)],"little"))
        save_file_at_dir(lookup[0][str(dev.address)+str(sender.handle)],str(datetime.now().strftime("%Y.%m.%d"))+".txt",tmp_data)
    elif len(data)==1:
        save_file_at_dir(lookup[0][str(dev.address)+str(sender.handle)],str(datetime.now().strftime("%Y.%m.%d"))+".txt",int.from_bytes(data,"little"))
    else:
#         print(f"{sender}: {data}")
        pcm = adpcm_decode(data)
        pcm_buffer[str(dev.address)+str(sender.handle)].extend(pcm)
#        pcm_buffer.extend(pcm)
#        print(len(pcm_buffer))
        if(len(pcm_buffer[str(dev.address)+str(sender.handle)]) >= 160000) :
#        if(len(pcm_buffer) >= 160000) :
            #print(f"{sender}: wav saved")
            sf.write(lookup[0][str(dev.address)+str(sender.handle)]+"/"+str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))+".wav", pcm_buffer[str(dev.address)+str(sender.handle)], 16000, 'PCM_16')
#            sf.write(lookup[0][str(dev.address)+str(sender.handle)]+"/"+str(datetime.now().strftime("%Y.%m.%d.%H.%M.%S"))+".wav", pcm_buffer, 16000, 'PCM_16')
            pcm_buffer[str(dev.address)+str(sender.handle)].clear()
#            pcm_buffer.clear()
     
def disconnected_callback(client):
    print(f'Device {client.address} disconnected')

async def work(dev):
    while True:
        try:
            async with BleakClient(dev.address) as client:
                
                client.set_disconnected_callback(disconnected_callback)
                services = await client.get_services()
                for service in services:
                    for characteristic in service.characteristics:
                        try:
                            # print('  uuid:', characteristic.uuid)
                            # print('  handle:', characteristic.handle) 
                            # print('  properties: ', characteristic.properties)
                            path=os.getcwd()+"/data"
                            for i in range(1,4):
                                if i==3:
                                    path=os.path.join(path,dev.name.split("_")[1])
                                if lookup[i].get(characteristic.uuid.split("-")[i]) !=None:
                                    path=os.path.join(path,lookup[i].get(characteristic.uuid.split("-")[i]))
                                    if lookup[i].get(characteristic.uuid.split("-")[i]) == "SOUND":
                                        pcm_buffer[str(dev.address)+str(characteristic.handle)]=[]
                                        #print(pcm_buffer)
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
            #print("connection retry")
            pass
            

task_list = []
async def main():
#    target_device=await scan()
#    print(target_device)
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

def save_file_at_dir(dir_path, filename, file_content, mode='a'):
    with open(os.path.join(dir_path, filename), mode) as f:     
        if "list" in str(type(file_content)):
            data_str=str(file_content[0])+"."+str(file_content[1])+","+\
            str(file_content[2])+"."+str(file_content[3])+","+\
            str(file_content[4])+"."+str(file_content[5])+","+\
            str(file_content[6])+"."+str(file_content[7])
            f.write(datetime.now().strftime("%X")+":    "+data_str+"\n")
        else:
            f.write(datetime.now().strftime("%X")+":    "+str(file_content)+"\n")

if __name__ == "__main__":
    print("run main")
    asyncio.run(main())
        
