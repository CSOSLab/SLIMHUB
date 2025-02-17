class Node:
    def __init__(self, name):
        self.name = name
        self.edges = {}
        self.activated = False

    def add_edge(self, neighbor, weight):
        self.edges[neighbor] = weight

    def activate(self):
        self.activated = True

    def deactivate(self):
        self.activated = False

    def check_activation(self):
        return "Active" if self.activated else "Inactive"

class CustomGraph:
    def __init__(self):
        self.nodes = {}

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
            
    # [New code] 간략하게 활성 노드 상태만 표시하는 함수 (display_graph_lite)
    def display_graph_lite(self):
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
        print(header)
        print(status)
            
            

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