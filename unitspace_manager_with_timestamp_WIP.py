# -*- coding: utf-8 -*-
from datetime import datetime
import os
import asyncio
import heapq  # 다익스트라 알고리즘을 위한 heapq 모듈

# 상수 정의 (각 집의 환경에 맞게 수정 가능)
ENTER_SIGNAL = 10
EXIT_SIGNAL = 20
NOISE_THRESHOLD = 10         # 동일 공간 내 신호 간 최소 간격 (초)
INACTIVITY_TIMEOUT = 30      # 강제 exit 시간 (테스트용 30초)
EXIT_VERIFYING_TIME = 20     # 동일 노드에서 재신호 시 exit 판단 시간 (초)

# 각 단위 공간(노드)를 표현하는 클래스
class Node:
    def __init__(self, name):
        self.name = name
        self.edges = {}  # neighbor_name -> 이동 가중치(초)
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

# 단위 공간 간 연결 관계를 관리하는 커스텀 그래프 클래스
class CustomGraph:
    def __init__(self, timeout_buffer=5):
        self.nodes = {}
        # address -> (location, last_time, state)
        # state: True면 활성 상태, False면 강제 exit되었거나 미확인 상태
        self.connected_devices_unitspace_process = {}
        # 각 이동에 대한 pending_moves 리스트
        self.pending_moves = []  # 각 항목: {from, to, start_time, timeout}
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

    def clear_all_activation(self):
        for node in self.nodes.values():
            node.deactivate()
        print("[CLEAR] All nodes deactivated.")

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

    # --- 추가된 부분: 다익스트라 알고리즘을 사용하여 시작 노드로부터 모든 도착 노드까지의 최단 이동시간(총 가중치)를 계산 ---
    def get_all_reachable_nodes(self, start_node):
        distances = {node: float('inf') for node in self.nodes}
        distances[start_node] = 0
        visited = set()
        pq = [(0, start_node)]
        while pq:
            d, current = heapq.heappop(pq)
            if current in visited:
                continue
            visited.add(current)
            for neighbor, weight in self.nodes[current].edges.items():
                if neighbor not in visited:
                    new_dist = d + weight
                    if new_dist < distances[neighbor]:
                        distances[neighbor] = new_dist
                        heapq.heappush(pq, (new_dist, neighbor))
        return distances
    # --- 끝 ---

    # --- 수정된 부분: pending_moves에 다중 경로(2칸 이상 연결된 노드 포함)를 추가 ---
    def add_pending_moves(self, from_node, received_time):
        self.pending_moves = []  # 기존 pending_moves 초기화
        if from_node in self.nodes:
            # 다익스트라 알고리즘을 통해 from_node로부터 모든 도착 노드까지의 최단 이동시간을 계산
            reachable = self.get_all_reachable_nodes(from_node)
            for dest, total_weight in reachable.items():
                if dest == from_node:
                    continue
                timeout = total_weight + self.timeout_buffer
                self.pending_moves.append({
                    "from": from_node,
                    "to": dest,
                    "start_time": received_time,
                    "timeout": timeout
                })
                print(f"[PENDING] Possible move from {from_node} to {dest} with total travel time {total_weight}s, timeout={timeout}s")
    # --- 끝 ---

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
        # 만약 타임아웃된 이동이 있다면, 첫번째 pending move의 'from'으로 강제 복귀
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

# 단위 공간 상태를 관리하는 메인 매니저 클래스
class UnitspaceManager_new:
    ENTER = ENTER_SIGNAL
    EXIT = EXIT_SIGNAL

    def __init__(self):
        self.graph = CustomGraph(timeout_buffer=5)
        # 집 구조에 따른 노드 및 에지 설정
        self.graph.add_edge("ENTRY", "LIVING", 10)
        self.graph.add_edge("LIVING", "TOILET", 5)
        self.graph.add_edge("LIVING", "KITCHEN", 10)
        self.graph.add_edge("LIVING", "BEDROOM", 10)
        self.graph.add_edge("LIVING", "ROOM", 15)
        # 초기 활성 노드는 LIVING으로 설정 (테스트 코드이므로 불일치 가능)
        self.graph.set_active_node("LIVING", force_activate=True)
        self.inactivity_timeout = INACTIVITY_TIMEOUT

    async def pending_move_timeout_checker(self, interval=1):
        from device import get_device_by_address  # 단말 객체 획득 (외부 모듈)
        while True:
            current_time = datetime.now().timestamp()
            # pending move 타임아웃 확인
            self.graph.check_pending_moves_timeout(current_time)
            # 연결된 단말들의 inactivity 여부 확인 (상태와 상관없이 마지막 신호 기준)
            addresses_to_remove = []
            for address, (location, last_time, state) in list(self.graph.connected_devices_unitspace_process.items()):
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
        # 파라미터 시그니처는 그대로 유지 (내용만 수정 가능)
        if service_name != "inference":
            return

        from device import get_device_by_address
        device_obj = get_device_by_address(address)
        received_signal = unpacked_data_list[1]
        graph = self.graph

        # === [추가된 부분] ===
        # 현재 device record가 존재하는 경우, 수신된 신호의 location이 기록된 현재 위치와 다르고
        # 신호가 EXIT라면 이는 오래된(유효하지 않은) 신호로 판단하여 무시합니다.
        if address in graph.connected_devices_unitspace_process:
            current_location, last_time, state = graph.connected_devices_unitspace_process[address]
            if received_signal == self.EXIT and location != current_location:
                print(f"[IGNORE] Outdated EXIT signal from {location} while current location is {current_location}.")
                return
        # === 끝 ===

        # 기존 device가 존재하는 경우
        if address in graph.connected_devices_unitspace_process:
            prev_location, last_time, state = graph.connected_devices_unitspace_process[address]
            if location == prev_location:
                time_diff = received_time - last_time
                # NOISE_THRESHOLD 이하: 단순 중복 신호로 무시
                if time_diff < NOISE_THRESHOLD:
                    print(f"[IGNORE] Redundant signal in {location} within {NOISE_THRESHOLD}s.")
                    graph.record_activation_time(location, received_time)
                    graph.connected_devices_unitspace_process[address] = (location, received_time, state)
                    return
                # NOISE_THRESHOLD 이상, EXIT_VERIFYING_TIME 미만: 모호한 신호로 전체 활성 상태 초기화 및 로그 기록
                elif NOISE_THRESHOLD <= time_diff < EXIT_VERIFYING_TIME:
                    print(f"[CLEAR] Ambiguous signal in {location} ({time_diff}s), clearing all activations and logging state.")
                    graph.clear_all_activation()
                    graph.display_graph_lite(datetime.fromtimestamp(received_time))
                    graph.record_activation_time(location, received_time)
                    return
                # EXIT_VERIFYING_TIME 이상 경과 후 동일 노드 신호: 강제 exit로 판단
                elif time_diff >= EXIT_VERIFYING_TIME:
                    print(f"[EXIT VERIFYING] Signal from {location} after {EXIT_VERIFYING_TIME}s. Forcing exit (unknown next destination).")
                    graph.clear_all_activation()
                    graph.record_activation_time(location, received_time)
                    await device_obj.unitspace_existence_callback("strong_exit")
                    del graph.connected_devices_unitspace_process[address]
                    return

        # 신규 단말의 경우
        if address not in graph.connected_devices_unitspace_process:
            graph.connected_devices_unitspace_process[address] = (location, received_time, True)
            graph.set_active_node(location, force_activate=True)
            graph.record_activation_time(location, received_time)
            await device_obj.unitspace_existence_callback("strong_enter")
            return

        # 기존 단말이고, 신호가 다른 노드로 들어온 경우
        # 이 경우, valid pending move가 존재하는 ENTER 신호로 처리합니다.
        if received_signal == self.ENTER:
            pending_moves = graph.pending_moves
            if not pending_moves:
                print(f"[UNEXPECTED] ENTER at {location} (no pending move).")
                graph.set_active_node(location, force_activate=True)
                graph.record_activation_time(location, received_time)
                graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                await device_obj.unitspace_existence_callback("weak_enter")
                self.update_graph_state(address, location, received_time)
                return

            # pending_moves 중 해당 위치로의 이동 확인
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
                    # === [변경된 부분] ===
                    # valid move 성공 시 device record를 즉시 새로운 location으로 업데이트합니다.
                    graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                    # === 끝 ===
                    graph.clear_pending_moves()
                    await device_obj.unitspace_existence_callback("strong_enter")
                else:
                    print(f"[TIMEOUT] Move to {location} exceeded timeout ({elapsed}s).")
                    graph.set_active_node(location, force_activate=True)
                    graph.record_activation_time(location, received_time)
                    graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                    graph.clear_pending_moves()
                    await device_obj.unitspace_existence_callback("weak_enter")
                self.update_graph_state(address, location, received_time)
            else:
                # pending move와 일치하지 않는 ENTER 신호
                print(f"[INVALID] Unexpected ENTER at {location}.")
                graph.set_active_node(location, force_activate=True)
                graph.record_activation_time(location, received_time)
                graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                graph.clear_pending_moves()
                await device_obj.unitspace_existence_callback("weak_enter")
                self.update_graph_state(address, location, received_time)
        else:
            # EXIT 신호인 경우, 위에서 처리되었거나(동일 공간, 중복 등) 이미 새로운 노드로 갱신되었어야 합니다.
            pass

    def update_graph_state(self, address, location, timestamp):
        graph = self.graph
        if location not in graph.nodes:
            print(f"[ERROR] Unknown location: {location}")
            return
        # 지정된 location만 활성화, 나머지는 deactivation
        for node_name, node in graph.nodes.items():
            if node_name == location:
                node.activate()
            else:
                node.deactivate()
        graph.record_activation_time(location, timestamp)
        if address in graph.connected_devices_unitspace_process:
            graph.connected_devices_unitspace_process[address] = (location, timestamp, True)
        graph.display_graph_lite(datetime.fromtimestamp(timestamp))
