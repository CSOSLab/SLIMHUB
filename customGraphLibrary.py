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