# -*- coding: utf-8 -*-
from datetime import datetime
import os
import asyncio

# 상수 정의
EXIT_SIGNAL = 20
ENTER_SIGNAL = 10
INACTIVITY_TIMEOUT = 30  # 마지막 신호 이후 강제 exit (초)
NOISE_THRESHOLD = 15       # 같은 공간 내 신호 무시 기준 (초)


# 각 단위 공간(노드)를 표현하는 클래스
class Node:
    def __init__(self, name):
        self.name = name
        self.edges = {}  # neighbor_name -> 이동 가중치(시간)
        self.last_active_time = 0
        self.activated = False

    def add_edge(self, neighbor, weight):
        self.edges[neighbor] = weight

    def activate(self):
        self.activated = True

    def deactivate(self):
        self.activated = False

    def record_time(self, time_val):
        self.last_active_time = time_val

    def get_last_active_time(self):
        return self.last_active_time

# 단위 공간 간의 연결관계를 관리하는 커스텀 그래프 클래스
class CustomGraph:
    def __init__(self, timeout_buffer=5):
        self.nodes = {}
        # address -> (location, last_time, active_state)
        self.connected_devices_unitspace_process = {}
        # 각 이동에 대한 pending_moves 리스트 (각 항목: {from, to, start_time, timeout})
        self.pending_moves = []
        self.timeout_buffer = timeout_buffer

    def add_node(self, name):
        if name not in self.nodes:
            self.nodes[name] = Node(name)

    def add_edge(self, from_node, to_node, weight):
        self.add_node(from_node)
        self.add_node(to_node)
        self.nodes[from_node].add_edge(to_node, weight)
        self.nodes[to_node].add_edge(from_node, weight)

    def set_active_node(self, name, force_activate=False):
        if name not in self.nodes:
            print(f"[WARNING] Node '{name}' not found.")
            return
        if force_activate:
            for node in self.nodes.values():
                node.deactivate()
            self.nodes[name].activate()
            print(f"[FORCE] Node '{name}' activated.")
        else:
            for node in self.nodes.values():
                node.deactivate()
            self.nodes[name].activate()

    def activate_node(self, name):
        if name in self.nodes:
            self.nodes[name].activate()

    def deactivate_node(self, name):
        if name in self.nodes:
            self.nodes[name].deactivate()

    def record_activation_time(self, name, time_val):
        if name in self.nodes:
            self.nodes[name].record_time(time_val)

    def get_last_active_time(self, name):
        if name in self.nodes:
            return self.nodes[name].get_last_active_time()
        return None

    def add_pending_moves(self, from_node, received_time):
        self.pending_moves = []  # 기존 pending_moves 초기화
        if from_node in self.nodes:
            for dest, move_time in self.nodes[from_node].edges.items():
                timeout = move_time + self.timeout_buffer
                self.pending_moves.append({
                    "from": from_node,
                    "to": dest,
                    "start_time": received_time,
                    "timeout": timeout
                })
                print(f"[PENDING] Possible move from {from_node} to {dest}, timeout={timeout}s")

    def clear_pending_moves(self):
        self.pending_moves = []

    def check_pending_moves_timeout(self, current_time):
        if not self.pending_moves:
            return
        expired_moves = []
        for move in self.pending_moves:
            elapsed = current_time - move["start_time"]
            if elapsed > move["timeout"]:
                print(f"[TIMEOUT] Move from {move['from']} to {move['to']} expired (elapsed {elapsed}s).")
                expired_moves.append(move)
        # 만약 타임아웃된 이동이 있다면, 첫번째 pending move의 from으로 강제 복귀
        if expired_moves:
            forced_node = expired_moves[0]["from"]
            self.set_active_node(forced_node, force_activate=True)
            self.record_activation_time(forced_node, current_time)
            self.clear_pending_moves()

    def display_graph_lite(self, time_dt):
        node_names = list(self.nodes.keys())
        col_width = max(len(n) for n in node_names) + 4
        header = " ".join([f"[ {name:^{col_width-2}} ]" for name in node_names])
        status = " ".join([
            f"[ {'***' if self.nodes[n].activated else '--':^{col_width-2}} ]"
            for n in node_names
        ])
        filename = time_dt.strftime("%Y-%m-%d") + ".txt"
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "data", "display")
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, filename), 'a') as f:
            f.write(header + "\n" + status + "\n")


class UnitspaceManager_new_new:
    ACTIVE = ENTER_SIGNAL
    
    def __init__(self):
        self.lock = asyncio.Lock()
        self.last_address = None
        self.last_location = None
        self.last_received_time = 0
        self.active_count = 0
        
        self.graph = CustomGraph()
        self.graph.add_edge("LIVING", "ENTRY", 10)
        self.graph.add_edge("LIVING", "TOILET", 10)
        self.graph.add_edge("LIVING", "KITCHEN", 10)
        self.graph.add_edge("LIVING", "BEDROOM", 10)
        
        self.graph.add_edge("ENTRY", "TOILET", 10)
        self.graph.add_edge("ETNRY", "KITCHEN", 10)
        self.graph.add_edge("ENTRY", "BEDROOM", 10)
        
        self.graph.add_edge("TOILET", "KITCHEN", 10)
        self.graph.add_edge("TOILET", "BEDROOM", 10)
        
        self.graph.add_edge("KITCHEN", "BEDROOM", 10)
        
    async def unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        if service_name != "inference":
            return
        
        async with self.lock:
            from device import get_device_by_address
            current_device_obj = get_device_by_address(address)
            current_received_time = datetime.now().timestamp()
            received_signal = unpacked_data_list[1]
            graph = self.graph
            
            # Test code
            if received_signal == 10:
                if (self.last_address != None) or (self.last_location != None):
                    # print(f"{location} - Active signal reacehed {self.last_location}")
                    self.active_count += 1
                if address == self.last_address:
                    if current_received_time - self.last_received_time >= 120:
                        print(f"Exceeded time out (120s) - send exit signal")
                        await current_device_obj.unitspace_existence_callback("strong_exit")
                    else:
                        # print(f"{location} Noise filtered or wandering under the sensor")
                        return
                elif address != self.last_address:
                    print(f"From \"{self.last_location}\" to \"{location}\" moved")
                    await current_device_obj.unitspace_existence_callback("strong_enter")
                    
                    if self.last_address is not None:
                        last_device_obj = get_device_by_address(self.last_address)
                        if last_device_obj is not None:
                            await last_device_obj.unitspace_existence_callback("strong_exit")
                            print("Exit signal sended")
            elif received_signal == 20:
                print(f"{location} - Active signal reacehed")
                await current_device_obj.unitspace_existence_callback("strong_exit")
                
            self.last_address = address
            self.last_location = location
            self.last_received_time = current_received_time
            self.active_count = 0   # redundant value
            
        
# 단위 공간 상태를 관리하는 메인 매니저 클래스
class UnitspaceManager_new:
    ENTER = ENTER_SIGNAL
    EXIT = EXIT_SIGNAL

    def __init__(self):
        self.graph = CustomGraph(timeout_buffer=5)
        # 집 구조에 따른 노드 및 에지 설정
        self.graph.add_edge("LIVING", "ENTRY", 10)
        self.graph.add_edge("LIVING", "TOILET", 5)
        self.graph.add_edge("LIVING", "KITCHEN", 10)
        self.graph.add_edge("LIVING", "BEDROOM", 10)
        
        self.graph.add_edge("ENTRY", "TOILET", 10)
        self.graph.add_edge("ETNRY", "KITCHEN", 20)
        self.graph.add_edge("ENTRY", "BEDROOM", 20)
        
        self.graph.add_edge("TOILET", "KITCHEN", 20)
        self.graph.add_edge("TOILET", "BEDROOM", 20)
        
        self.graph.add_edge("KITCHEN", "BEDROOM", 15)
        # 초기 활성 노드는 LIVING으로 설정
        self.graph.set_active_node("LIVING", force_activate=True)
        self.inactivity_timeout = INACTIVITY_TIMEOUT

    async def pending_move_timeout_checker(self, interval=1):
        from device import get_device_by_address  # (모듈 임포트)
        while True:
            current_time = datetime.now().timestamp()
            # pending move들의 타임아웃 여부 확인
            self.graph.check_pending_moves_timeout(current_time)
            # 각 연결된 단말의 inactivity(신호 없음) 여부 확인
            addresses_to_remove = []
            for address, (location, last_time, state) in list(self.graph.connected_devices_unitspace_process.items()):
                if self.graph.nodes.get(location) and self.graph.nodes[location].activated:
                    if current_time - last_time > self.inactivity_timeout:
                        print(f"[INACTIVITY TIMEOUT] No signal from device {address} in {current_time - last_time:.0f}s. Forcing exit from {location}.")
                        self.graph.deactivate_node(location)
                        self.graph.record_activation_time(location, current_time)
                        device_obj = get_device_by_address(address)
                        asyncio.create_task(device_obj.unitspace_existence_callback("strong_exit"))
                        addresses_to_remove.append(address)
            for address in addresses_to_remove:
                del self.graph.connected_devices_unitspace_process[address]
            await asyncio.sleep(interval)

    async def unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        # 파라미터 signature는 변경하지 않음
        if service_name != "inference":
            return
        
        global last_address
        if last_address == None:
            print("[INIT] First input.")
            last_address = address
            

        from device import get_device_by_address
        device_obj = get_device_by_address(address)
        received_signal = unpacked_data_list[1]
        graph = self.graph

        # 동일 단위 공간 내에서의 불필요한 신호(노이즈/배회) 무시
        if address in graph.connected_devices_unitspace_process:
            prev_location, last_time, state = graph.connected_devices_unitspace_process[address]
            if location == prev_location:
                if received_time - last_time < NOISE_THRESHOLD:
                    print(f"[IGNORE] Redundant signal in {location} within {NOISE_THRESHOLD}s.")
                    graph.record_activation_time(location, received_time)
                    graph.connected_devices_unitspace_process[address] = (location, received_time, state)
                    return

        # 신규 단말의 경우
        if address not in graph.connected_devices_unitspace_process:
            graph.connected_devices_unitspace_process[address] = (location, received_time, True)
            graph.set_active_node(location, force_activate=True)
            graph.record_activation_time(location, received_time)
            await device_obj.unitspace_existence_callback("strong_enter")
            return

        prev_location, last_time, state = graph.connected_devices_unitspace_process[address]

        if received_signal == self.EXIT:
            # 같은 공간에서의 짧은 간격 EXIT 신호는 무시
            if location == prev_location and received_time - last_time < NOISE_THRESHOLD:
                print(f"[IGNORE] Redundant EXIT signal in {location} within {NOISE_THRESHOLD}s.")
                graph.record_activation_time(location, received_time)
                graph.connected_devices_unitspace_process[address] = (location, received_time, state)
                return

            # EXIT 신호 수신 시 현재 공간 비활성화 및 인접 공간 이동 후보(pending_moves) 설정
            graph.deactivate_node(prev_location)
            graph.record_activation_time(prev_location, received_time)
            graph.add_pending_moves(prev_location, received_time)
            # await device_obj.unitspace_existence_callback("strong_exit")
            if not address == last_address:
                await device_obj.unitspace_existence_callback("weak_enter")
            last_device_obj = get_device_by_address(last_address)
            await last_device_obj.unitspace_existence_callback("strong_exit")
            self.update_graph_state(address, prev_location, received_time)
            last_address = address
            return

        elif received_signal == self.ENTER:
            pending_moves = graph.pending_moves
            if not pending_moves:
                # pending move가 없으면 예상치 못한 ENTER로 판단 (weak_enter)
                print(f"[UNEXPECTED] ENTER at {location} (no pending move).")
                graph.set_active_node(location, force_activate=True)
                graph.record_activation_time(location, received_time)
                graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                if not address == last_address:
                    await device_obj.unitspace_existence_callback("weak_enter")         ## must be fixed later!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
                last_device_obj = get_device_by_address(last_address)
                await last_device_obj.unitspace_existence_callback("strong_exit")
                self.update_graph_state(address, location, received_time)
                last_address = address
                return

            # pending_moves 중 일치하는 이동이 있는지 확인
            valid_move = None
            for move in pending_moves:
                if move["to"] == location:
                    valid_move = move
                    break

            if valid_move:
                elapsed = received_time - valid_move["start_time"]
                if elapsed <= valid_move["timeout"]:
                    print(f"[SUCCESS] Move from {valid_move['from']} to {location}, elapsed {elapsed}s.")
                    graph.set_active_node(location, force_activate=True)
                    graph.record_activation_time(location, received_time)
                    graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                    graph.clear_pending_moves()
                    if not address == last_address:
                        await device_obj.unitspace_existence_callback("strong_enter")
                    last_device_obj = get_device_by_address(last_address)
                    await last_device_obj.unitspace_existence_callback("strong_exit")
                else:
                    print(f"[TIMEOUT] Move to {location} exceeded timeout ({elapsed}s).")
                    graph.set_active_node(location, force_activate=True)
                    graph.record_activation_time(location, received_time)
                    graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                    graph.clear_pending_moves()
                    if not address == last_address:
                        await device_obj.unitspace_existence_callback("weak_enter")
                    last_device_obj = get_device_by_address(last_address)
                    await last_device_obj.unitspace_existence_callback("strong_exit")
                self.update_graph_state(address, location, received_time)
                last_address = address
            else:
                # pending move와 일치하지 않는 ENTER 신호인 경우
                print(f"[INVALID] Unexpected ENTER at {location}.")
                graph.set_active_node(location, force_activate=True)
                graph.record_activation_time(location, received_time)
                graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                graph.clear_pending_moves()
                if not address == last_address:
                    await device_obj.unitspace_existence_callback("weak_enter")
                last_device_obj = get_device_by_address(last_address)
                await last_device_obj.unitspace_existence_callback("strong_exit")
                self.update_graph_state(address, location, received_time)
                last_address = address
        # print(f"Current input : {address}, Last input : {last_address}")
        # last_address = address

    def update_graph_state(self, address, location, timestamp):
        graph = self.graph
        if location not in graph.nodes:
            print(f"[ERROR] Unknown location: {location}")
            return
        # 지정된 location만 활성화, 나머지는 비활성화
        for node_name, node in graph.nodes.items():
            if node_name == location:
                node.activate()
            else:
                node.deactivate()
        graph.record_activation_time(location, timestamp)
        if address in graph.connected_devices_unitspace_process:
            graph.connected_devices_unitspace_process[address] = (location, timestamp, True)
        graph.display_graph_lite(datetime.fromtimestamp(timestamp))
