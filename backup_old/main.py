import asyncio
import os
from bleak import *
from datetime import datetime
from functools import partial
import numpy as np
import time
import struct
import json
import socket
import select
import argparse
from threading import Thread
# from multiprocessing import Manager
import logging
import signal

import device

from process import *
from dean_uuid import *

host = 'localhost'
port = 6604

sound_process = SoundProcess()
data_process = DataProcess()
unitspace_process = UnitspaceProcess()


manager = device.DeviceManager()

logging.basicConfig(filename=os.path.dirname(os.path.realpath(__file__))+'/programdata/logging.log', format='%(asctime)s: %(levelname)s: %(message)s', level=logging.INFO)

term_flag = False

async def main_worker(server):
    async def scan():
        target_devices = []
        try:
            devices = await BleakScanner.discover(return_adv=True, timeout=2)
        except Exception as e:
            logging.warning(e)
            return None
        else:
            for dev in devices.values():
                if DEAN_UUID_BASE_SERVICE in dev[1].service_uuids:
                    target_devices.append(dev[0])
            return target_devices
    
    while True:
        if term_flag:
            server.close()
            return
        
        target_devices = await scan()
        if target_devices is None:
            await asyncio.sleep(10)
            continue

        for dev in target_devices:
            current_device = device.get_device_by_address(dev.address)
            if current_device is None:
                current_device = device.Device(dev)
                if current_device.config_dict['type'] == "DE&N":
                    current_device.manager_queue = manager.get_queue()
                    current_device.sound_queue = sound_process.get_queue()
                    current_device.data_queue = data_process.get_queue()
                    current_device.unitspace_queue = unitspace_process.get_queue()

                if await current_device.ble_client_start():
                    logging.info('%s connected', dev)
                else:
                    logging.info('%s connection failed', dev)

            else:
                if await current_device.ble_client_start():
                    logging.info('%s reconnected', dev)
                else:
                    logging.info('%s reconnection failed', dev)

            await asyncio.sleep(0.1)

        await asyncio.sleep(10)

async def cli_handler(reader, writer):
    def parse_message(msg):
        data = msg.decode()
        data = data.replace('\'', '')
        data = data[1:-1]
        data = data.split(', ')
        return data
    
    try:
        msg = await reader.read(1024)
        data = parse_message(msg)

        if data[0] == 'quit':
            logging.info('Client requested server shutdown')
            writer.write('Shutting down server'.encode())
            await writer.drain()
            global term_flag
            term_flag = True
        else:
            return_msg = await manager.process_command(data)
            writer.write(return_msg)
            await writer.drain()
    except asyncio.CancelledError:
        pass
    finally:
        writer.close()

def send_command(cmd, args_dict):
    s = socket.socket(socket.AF_INET)
    try:
        s.connect((host, port))
    except:
        print("Slimhub server is not running")
        sys.exit(0)
    if type(args_dict[cmd]) == bool:
        s.send(str([cmd]).encode())
    elif type(args_dict[cmd]) == list:
        args_dict[cmd].insert(0, cmd)
        s.send(str(args_dict[cmd]).encode())
    data = s.recv(4096)
    print(data.decode())

async def async_main():
    server = await asyncio.start_server(cli_handler, host, port)
    main_task = asyncio.create_task(main_worker(server))

    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        await main_task

        sound_process.stop()
        data_process.stop()
        unitspace_process.stop()
        sound_process.process.join()
        data_process.process.join()
        unitspace_process.process.join()
        
        return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slimhub service")
    parser.add_argument('-r', '--run', action='store_true', help='run slimhub client')
    parser.add_argument('-c', '--config', nargs=3, help='configure device', 
                        metavar=('address', 'target', 'data'))
    parser.add_argument('-s', '--service', nargs=4, help='manage characteristic notification', 
                        metavar=('address', 'enable/disable', 'service', 'characteristic'))
    parser.add_argument('-u', '--update', nargs=1, help='update device model',
                        metavar=('address'))
    parser.add_argument('-f', '--feature', nargs=2, help='sound feature collection',
                        metavar=('address', 'start/stop'))
    parser.add_argument('-t', '--train', nargs=1, help='train sound model',
                        metavar=('address'))
    parser.add_argument('-a', '--apply', action='store_true', help='apply config file')
    parser.add_argument('-l', '--list', action='store_true', help='list registered devices')
    parser.add_argument('-q', '--quit', action='store_true', help='quit slimhub client')
    
    parser.add_argument('-us', '--unitspace', nargs=1, help='unitspace existence estimation service',
                        metavar=('address'))

    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(0)

    args = parser.parse_args()
    args_dict = vars(args)

    if args.run:
        sound_process.start()
        data_process.start()
        unitspace_process.start()

        asyncio.run(async_main())
        logging.info('Exiting slimhub server')
    
    if args.config:
        send_command('config', args_dict)
    
    if args.service:
        send_command('service', args_dict)

    if args.update:
        send_command('update', args_dict)

    if args.feature:
        send_command('feature', args_dict)
    
    if args.train:
        send_command('train', args_dict)
    
    if args.apply:
        send_command('apply', args_dict)

    if args.list:
        send_command('list', args_dict)

    if args.quit:
        send_command('quit', args_dict)
        
    if args.unitspace:
        send_command('unitspace', args_dict)