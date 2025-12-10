from datetime import datetime
import os

class Node:
    def __init__(self, name):
        self.name = name
        self.edges = {}
        self.last_active_time = 0
        self.activated = False

    def add_edge(self, neighbor, weight):
        self.edges[neighbor] = weight

    def activate(self):
        self.activated = True

    def deactivate(self):
        self.activated = False

    def check_activation(self):
        return "Active" if self.activated else "Inactive"
    
    def record_time(self, time):
        self.last_active_time = time
        
    def get_record_time_by_name(self):
        return self.last_active_time

class CustomGraph:
    def __init__(self):
        self.nodes = {}
        self.connected_devices_unitspace_process = {}

    def add_node(self, name):
        if name not in self.nodes:
            self.nodes[name] = Node(name)

    def add_edge(self, from_node, to_node, weight):
        if from_node not in self.nodes:
            self.add_node(from_node)
        if to_node not in self.nodes:
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
        return [node_name for node_name, node in self.nodes.items() if node.activated]
    
    def record_activation_time(self, name, time):
        if name in self.nodes:
            self.nodes[name].record_time(time)
    
    def get_record_time_by_name(self, name):
        if name in self.nodes:
            return self.nodes[name].get_record_time()
        else:
            print(f"Node '{name}' not found in the graph.")
            return None
    
    

    def display_graph(self):
        node_names = list(self.nodes.keys())
        n = len(node_names)
        graph_matrix = [[0 for _ in range(n)] for _ in range(n)]

        for i, node_name in enumerate(node_names):
            node = self.nodes[node_name]
            for neighbor_name, weight in node.edges.items():
                j = node_names.index(neighbor_name)
                if node.activated:
                    graph_matrix[i][j] = f"{weight}*"  # 활성화된 경우 가중치에 "*" 추가
                else:
                    graph_matrix[i][j] = weight

        print("    ", "  ".join(node_names))
        for i, row in enumerate(graph_matrix):
            print(f"{node_names[i]} ", row)
            
    def display_graph_lite(self, time_dt):
        node_names = list(self.nodes.keys())
        if not node_names:
            print("No nodes.")
            return
        # 최대 노드 이름 길이 결정 (각 열의 최소 폭)
        max_width = max(len(name) for name in node_names)
        # 양쪽에 여유 공간을 위해 추가 폭 (예: 4)
        col_width = max_width + 4
        # 헤더: 각 노드 이름을 가운데 정렬하여 출력
        header_cells = [f"[ {name:^{col_width-2}} ]" for name in node_names]
        header = " ".join(header_cells)
        # 상태 행: 각 노드가 활성이면 "***", 아니면 "--"를 가운데 정렬하여 출력
        status_cells = []
        for name in node_names:
            status_symbol = "***" if self.nodes[name].activated else "--"
            status_cells.append(f"[ {status_symbol:^{col_width-2}} ]")
        status = " ".join(status_cells)

        # 경로 설정
        filename = time_dt.strftime("%Y-%m-%d") + ".txt"
        path_base = os.path.join(os.path.dirname(os.path.realpath(__file__)), "data")
        dir_path = os.path.join(path_base, "display")

        # 디렉터리 생성
        os.makedirs(dir_path, exist_ok=True)

        with open(os.path.join(dir_path, filename), 'a') as f:
            f.write(header)
            f.write("\n")
            f.write(status)
            f.write("\n")
        
    # [New code] 단 하나의 노드만 활성화하도록 업데이트하는 메서드
    def set_active_node(self, name):
        active_nodes = self.get_active_nodes()  # 활성화된 노드 이름의 리스트
        # [New code] 만약 새 노드가 이미 활성 상태라면, 토글 방식으로 비활성화
        if name in active_nodes:
            self.nodes[name].deactivate()
            print(f"[New code] Node '{name}' was active and now deactivated.")
        else:
            for node in self.nodes.values():
                node.deactivate()
            if name in self.nodes:
                self.nodes[name].activate()
            else:
                print(f"[New code] Node '{name}' not found in the graph.")


class UnitspaceManager():
    residents_house_graph = None
    ENTER = 10
    EXIT = 20
    # dictionary를 address: (location, received_time, state) 형식으로 관리 (state: True=active, False=inactive)
    

    def __init__(self):

        # 기존에는 Debug 용 그래프를 사용했지만, 여기서는 residents_house_graph를 unitspace tree로 사용
        self.residents_house_graph = CustomGraph()

        # ENTRY -> LIVINGROOM
        self.residents_house_graph.add_edge("ENTRY", "LIVING", 10)

        # LIVINGROOM -> 다른 공간들 (Star Topology)
        self.residents_house_graph.add_edge("LIVING", "TOILET", 5)
        self.residents_house_graph.add_edge("LIVING", "KITCHEN", 10)
        self.residents_house_graph.add_edge("LIVING", "BEDROOM", 10)
        self.residents_house_graph.add_edge("LIVING", "ROOM", 15)

        # 초기 활성 노드 지정 (LIVING으로)
        self.residents_house_graph.set_active_node("LIVING")

        # 초기에는 빈 dictionary로 시작 (address: (location, received_signal, state))
        now = datetime.now()
        # self.residents_house_graph.connected_devices_unitspace_process = {"LIVING", now, True}
        # self.residents_house_graph.connected_devices_unitspace_process = {"ENTRY", now, False}
        # self.residents_house_graph.connected_devices_unitspace_process = {"TOILET", now, False}
        # self.residents_house_graph.connected_devices_unitspace_process = {"KITCHEN", now, False}
        # self.residents_house_graph.connected_devices_unitspace_process = {"BEDROOM", now, False}
        # self.residents_house_graph.connected_devices_unitspace_process = {"ROOM", now, False}

    async def unitspace_existence_estimation(self, location, device_type, address, service_name, char_name, received_time, unpacked_data_list):
        time_dt = datetime.fromtimestamp(received_time)
        try:
            # Branches according to received signal and address
            if service_name == "inference":
                from device import get_device_by_address
                device_obj = get_device_by_address(address)
                
                # First entrance to the graph
                if address not in self.residents_house_graph.connected_devices_unitspace_process:
                    # slimhub based decision mode
                    if location in self.residents_house_graph.nodes:
                        self.residents_house_graph.connected_devices_unitspace_process[address] = (location, received_time, True)
                        write_command = ['internal_processing', str(address), "weak_enter"]
                    else:
                    # unregisted device : stand alone mode
                        received_signal  = unpacked_data_list[1]
                        if received_signal == self.ENTER:
                            write_command = ['internal_processing', str(address), "strong_enter"]
                            print(f"[ENTER] Resiter the device {address} by using slimhub --config control")
                        elif received_signal == self.EXIT:
                            write_command = ['internal_processing', str(address), "strong_exit"]
                            print(f"[EXIT] Resiter the device {address} by using slimhub --config control")
                # After first entrance to the graph
                else:
                    stored_location, last_activation_time, current_state = self.residents_house_graph.connected_devices_unitspace_process[address]
                    received_signal = unpacked_data_list[1]
                    
                    if current_state:   # active
                        time_difference = received_time - last_activation_time
                        print(time_difference)
                        if time_difference > self.residents_house_graph.nodes(stored_location):
                            print("too short")
                            
                            
                    

                # # First check : is received device is registered in "self.residents_house_graph"
                # if address not in self.residents_house_graph.connected_devices_unitspace_process:
                #     # 만약 해당 device의 location이 residents_house_graph에 등록되어 있다면,
                #     # weak_enter 신호 대신 "ROOM"을 초기 활성 노드로 지정.
                #     if location in self.residents_house_graph.nodes:
                #         self.residents_house_graph.connected_devices_unitspace_process[address] = (location, True)
                #         # 초기 활성 노드를 "ROOM"으로 설정
                #         self.residents_house_graph.set_active_node("ROOM")
                #         write_command = ['internal_processing', str(address), "weak_exit"]
                #         print(f"[New code] Initial connection for {address} in graph: setting ROOM as active node. (No weak_enter sent)")
                #     else:
                #         # 만약 location이 graph에 없다면, 기존대로 weak_enter 명령 전송
                #         self.residents_house_graph.connected_devices_unitspace_process[address] = (location, True)
                #         write_command = ['internal_processing', str(address), "weak_enter"]
                #         print(f"[New code] Initial connection for {address}: sending weak_enter")
                # else:
                #     # [New code] 이미 등록되어 있는 경우: 기존 state 확인
                #     stored_location, current_state = self.residents_house_graph.connected_devices_unitspace_process[address]
                #     received_signal = unpacked_data_list[1]

                #     if current_state:  # active 상태
                #         if received_signal == 10:
                #             # (b) active 상태에서 signal 10 → weak_exit 전송, state inactive로 변경
                #             write_command = ['internal_processing', str(address), "weak_exit"]
                #             self.residents_house_graph.connected_devices_unitspace_process[address] = (stored_location, False)
                #             print(f"[New code] Active unitspace {address}: received signal 10, sending weak_exit and setting inactive")
                #         elif received_signal == 20:
                #             # (e) active 상태에서 signal 20 → strong_exit 전송, state inactive로 변경
                #             write_command = ['internal_processing', str(address), "strong_exit"]
                #             self.residents_house_graph.connected_devices_unitspace_process[address] = (stored_location, False)
                #             print(f"[New code] Active unitspace {address}: received signal 20, sending strong_exit and setting inactive")
                #         else:
                #             write_command = ['internal_processing', str(address), "default_action"]
                #             print(f"[New code] Active unitspace {address}: received signal {received_signal}, sending default_action")
                #     else:  # inactive 상태
                #         if received_signal == 10:
                #             # (c) inactive 상태에서 signal 10 → strong_enter 전송, state active로 변경
                #             write_command = ['internal_processing', str(address), "strong_enter"]
                #             self.residents_house_graph.connected_devices_unitspace_process[address] = (stored_location, True)
                #             print(f"[New code] Inactive unitspace {address}: received signal 10, sending strong_enter and setting active")
                #         elif received_signal == 20:
                #             # (d) inactive 상태에서 signal 20 → weak_enter 전송, state active로 변경
                #             write_command = ['internal_processing', str(address), "weak_enter"]
                #             self.residents_house_graph.connected_devices_unitspace_process[address] = (stored_location, True)
                #             print(f"[New code] Inactive unitspace {address}: received signal 20, sending weak_enter and setting active")
                #         else:
                #             write_command = ['internal_processing', str(address), "default_action"]
                #             print(f"[New code] Inactive unitspace {address}: received signal {received_signal}, sending default_action")

                await device_obj.unitspace_existence_callback(address, write_command[2])

                # # [New code] 명령 전송 (IPC)
                # reply_queue = self.reply_manager.Queue()  # 올바른 reply_manager 사용
                # # print("[New code] Sending IPC command:", write_command)
                # loop = asyncio.get_running_loop()
                # self.ipc_queue.put((write_command, reply_queue))
                # result = await loop.run_in_executor(None, reply_queue.get)
                # # print("[New code] Received IPC response:", result)
                # # [New code] 전달받은 location 정보로 그래프 업데이트:
                self.update_graph_state(address, location, time_dt)
        except Exception as e:
            print(f"Error: {e}")

    # [New code] graph 상태 업데이트 및 출력: residents_house_graph에 등록된 경우, 활성 노드를 업데이트하고 display_graph() 호출
    def update_graph_state(self, address, new_location, time_dt):
        if new_location in self.residents_house_graph.nodes:
            # [New code] 새로운 위치가 그래프에 있다면, 기존 활성 노드와 비교
            # 여기서는 단순히 새 위치로 업데이트하는 것으로 처리
            print(f"[New code] Updating graph state for {address}: setting active node to {new_location}")
            self.residents_house_graph.set_active_node(new_location)
            # self.residents_house_graph.display_graph()
            self.residents_house_graph.display_graph_lite(time_dt)
            # [New code] dictionary의 location 정보도 업데이트
            if address in self.residents_house_graph.connected_devices_unitspace_process:
                _, current_state = self.residents_house_graph.connected_devices_unitspace_process[address]
                self.residents_house_graph.connected_devices_unitspace_process[address] = (new_location, current_state)
        else:
            print(f"[New code] New location {new_location} not found in residents_house_graph.")
