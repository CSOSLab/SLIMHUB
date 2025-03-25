# -*- coding: utf-8 -*-
from datetime import datetime
import os
import asyncio

# 각 공간을 나타내는 노드 클래스
class Node:
    def __init__(self, name):
        self.name = name
        self.edges = {}  # 이웃 노드 및 이동 가중치
        self.last_active_time = 0  # 마지막 활성화 시간
        self.activated = False     # 현재 활성화 상태

    def add_edge(self, neighbor, weight):
        self.edges[neighbor] = weight

    def activate(self):
        self.activated = True

    def deactivate(self):
        self.activated = False

    def record_time(self, time):
        self.last_active_time = time

    def get_record_time(self):
        return self.last_active_time

# 공간 간 연결 정보를 가지는 사용자 정의 그래프 클래스
class CustomGraph:
    def __init__(self):
        self.nodes = {}
        self.connected_devices_unitspace_process = {}  # address -> (location, last_time, state)
        self.pending_move = None
        self.timeout_buffer = 5  # 초과 시간 허용

    def add_node(self, name):
        if name not in self.nodes:
            self.nodes[name] = Node(name)

    def add_edge(self, from_node, to_node, weight):
        self.add_node(from_node)
        self.add_node(to_node)
        self.nodes[from_node].add_edge(to_node, weight)
        self.nodes[to_node].add_edge(from_node, weight)

    def activate_node(self, name):
        if name in self.nodes:
            self.nodes[name].activate()

    def deactivate_node(self, name):
        if name in self.nodes:
            self.nodes[name].deactivate()

    def get_active_nodes(self):
        return [n for n, node in self.nodes.items() if node.activated]

    def record_activation_time(self, name, time):
        if name in self.nodes:
            self.nodes[name].record_time(time)

    def get_record_time_by_name(self, name):
        if name in self.nodes:
            return self.nodes[name].get_record_time()
        return None

    def check_pending_move_timeout(self, current_time):
        if self.pending_move is None:
            return
        elapsed = current_time - self.pending_move["start_time"]
        if elapsed > self.pending_move["timeout"]:
            print(f"[TIMEOUT] Move from {self.pending_move['from']} expired.")
            self.set_active_node(self.pending_move['from'], force_activate=True)
            self.pending_move = None

    def set_active_node(self, name, force_activate=False):
        if name not in self.nodes:
            print(f"[WARNING] Node '{name}' not found.")
            return
        if force_activate:
            for node in self.nodes.values():
                node.deactivate()
            self.nodes[name].activate()
            print(f"[FORCE] Node '{name}' activated.")
            return
        for node in self.nodes.values():
            node.deactivate()
        self.nodes[name].activate()
        print(f"[SET] Node '{name}' activated.")

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

# Unitspace 상태를 처리하는 메인 매니저 클래스
class UnitspaceManager_new:
    ENTER = 10
    EXIT = 20

    def __init__(self):
        self.residents_house_graph = CustomGraph()
        self._init_graph_structure()
        loop = asyncio.get_event_loop()
        loop.create_task(self.pending_move_timeout_checker())

    def _init_graph_structure(self):
        g = self.residents_house_graph
        g.add_edge("ENTRY", "LIVING", 10)
        g.add_edge("LIVING", "TOILET", 5)
        g.add_edge("LIVING", "KITCHEN", 10)
        g.add_edge("LIVING", "BEDROOM", 10)
        g.add_edge("LIVING", "ROOM", 15)
        g.set_active_node("LIVING")

    async def pending_move_timeout_checker(self, interval=1):
        while True:
            now = datetime.now().timestamp()
            self.residents_house_graph.check_pending_move_timeout(now)
            await asyncio.sleep(interval)

    async def unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        if service_name != "inference":
            return
        from device import get_device_by_address
        device_obj = get_device_by_address(address)
        received_signal = unpacked_data_list[1]
        graph = self.residents_house_graph
        
        if address not in graph.connected_devices_unitspace_process:
            graph.connected_devices_unitspace_process[address] = (location, received_time, True)
            graph.set_active_node(location, force_activate=True)
            graph.record_activation_time(location, received_time)
            await device_obj.unitspace_existence_callback("strong_enter")
            return

        prev_location, last_time, state = graph.connected_devices_unitspace_process[address]

        if received_signal == self.EXIT:
            neighbors = graph.nodes[prev_location].edges
            for dest in neighbors:
                timeout = neighbors[dest] + graph.timeout_buffer
                graph.pending_move = {
                    "from": prev_location,
                    "to": dest,
                    "start_time": received_time,
                    "timeout": timeout
                }
                print(f"[PENDING] Move from {prev_location} to {dest}, timeout={timeout}s")
                break
            graph.deactivate_node(prev_location)
            graph.record_activation_time(prev_location, received_time)
            await device_obj.unitspace_existence_callback("weak_exit")
            self.update_graph_state(address, prev_location, received_time)

        elif received_signal == self.ENTER:
            pending = graph.pending_move
            if pending is None:
                print(f"[UNEXPECTED] ENTER at {location} (no pending move)")
                graph.set_active_node(location, force_activate=True)
                graph.record_activation_time(location, received_time)
                graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                self.update_graph_state(address, location, received_time)
                return

            time_elapsed = received_time - pending["start_time"]
            if location == pending["to"] and time_elapsed <= pending["timeout"]:
                print(f"[SUCCESS] Move from {pending['from']} to {location}, {time_elapsed}s elapsed")
                graph.set_active_node(location, force_activate=True)
                graph.record_activation_time(location, received_time)
                graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                graph.pending_move = None
                await device_obj.unitspace_existence_callback("strong_enter")
                self.update_graph_state(address, location, received_time)
            elif time_elapsed > pending["timeout"]:
                print(f"[TIMEOUT] Move expired ({time_elapsed}s). Rolling back.")
                graph.set_active_node(pending['from'], force_activate=True)
                graph.record_activation_time(pending['from'], received_time)
                graph.connected_devices_unitspace_process[address] = (pending['from'], received_time, True)
                graph.pending_move = None

    def update_graph_state(self, address, location, timestamp):
        if location not in self.residents_house_graph.nodes:
            print(f"[ERROR] Unknown location {location}")
            return
        print(f"[GRAPH UPDATE] {address} → {location} at {timestamp}")
        self.residents_house_graph.set_active_node(location, force_activate=True)
        self.residents_house_graph.record_activation_time(location, timestamp)
        if address in self.residents_house_graph.connected_devices_unitspace_process:
            _, _, state = self.residents_house_graph.connected_devices_unitspace_process[address]
            self.residents_house_graph.connected_devices_unitspace_process[address] = (location, timestamp, state)
        self.residents_house_graph.display_graph_lite(datetime.fromtimestamp(timestamp))
