from dataclasses import dataclass
import matplotlib.pyplot as plt
import numpy as np
import struct
import heapq
import os

GRAPH_DIR = "Backend/DBMS/graphs"
FILE_DIR = "Backend/DBMS/data"

@dataclass
class Page:
    PAGE_ID: int
    DATA: bytearray

@dataclass
class PageHeader:
    IS_LEAF: bool
    N_ENTRIES: int
    PARENT_ID: int
PAGE_HEADER_FORMAT = "<?2i"
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)

@dataclass
class NodeEntry:
    MBR: tuple[float, float, float, float]  # (x1,y1,x2,y2)
    PTR: tuple[int, int] # (page_id, offset) para hojas, (page_id, 0) para nodos internos
NODE_ENTRY_FORMAT = "<4f2i"
NODE_ENTRY_SIZE = struct.calcsize(NODE_ENTRY_FORMAT)

class Node:
    def __init__(self, is_leaf: bool, entries: list[NodeEntry], page_id: int, parent_id: int = -1):
        self.IS_LEAF = is_leaf
        self.ENTRIES = entries
        self.PAGE_ID = page_id
        self.PARENT_ID = parent_id

    @staticmethod
    def from_page(page: Page) -> "Node":
        data = page.DATA
        is_leaf, n_entries, parent_id = struct.unpack_from(PAGE_HEADER_FORMAT, data, 0)

        entries = []
        offset = PAGE_HEADER_SIZE
        for _ in range(n_entries):
            x1, y1, x2, y2, p1, p2 = struct.unpack_from(NODE_ENTRY_FORMAT, data, offset)
            entry = NodeEntry(
                MBR=(x1, y1, x2, y2),
                PTR=(p1, p2)
            )
            entries.append(entry)
            offset += NODE_ENTRY_SIZE

        return Node(is_leaf, entries, page.PAGE_ID, parent_id)

    def to_page(self, page_size: int) -> Page:
        data = bytearray(page_size)
        n_entries = len(self.ENTRIES)
        struct.pack_into(PAGE_HEADER_FORMAT, data, 0, self.IS_LEAF, n_entries, self.PARENT_ID)

        offset = PAGE_HEADER_SIZE
        for entry in self.ENTRIES:
            x1, y1, x2, y2 = entry.MBR
            p1, p2 = entry.PTR
            struct.pack_into(
                NODE_ENTRY_FORMAT,
                data,
                offset,
                x1, y1, x2, y2, p1, p2
            )
            offset += NODE_ENTRY_SIZE

        return Page(self.PAGE_ID, data)
    
@dataclass
class FileHeader:
    PAGE_SIZE: int = 8192
    ROOT_PAGE: int = -1
    N_PAGES: int = 0
FILE_HEADER_FORMAT = "<3i"
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)


class RtreeFile:
    # FILE_HEADER = FileHeader
    # FILE_PATH = os.path.join(FILE_DIR, "RtreeFile.bin")
    # MAX_ENTRIES = (PAGE_SIZE - PAGE_HEADER_SIZE) // NODE_ENTRY_SIZE

    def __init__(self):
        os.makedirs(os.path.dirname(FILE_DIR), exist_ok=True)
        self.FILE_PATH = os.path.join(FILE_DIR, "RtreeFile.bin")
        try:
            self.read_file_header()
        except FileNotFoundError:
            self.FILE_HEADER = FileHeader()
            open(self.FILE_PATH, "ab").close()
            self.write_file_header()
        finally:
            self.MAX_ENTRIES = (self.FILE_HEADER.PAGE_SIZE - PAGE_HEADER_SIZE) // NODE_ENTRY_SIZE

    def read_page(self, page_id: int) -> Page:
        offset = self.FILE_HEADER_SIZE + page_id * self.FILE_HEADER.PAGE_SIZE

        with open(self.FILE_PATH, "rb") as file:
            file.seek(offset)
            data = file.read(self.FILE_HEADER.PAGE_SIZE)

            if len(data) != self.FILE_HEADER.PAGE_SIZE:
                raise ValueError("Página incompleta o inexistente")

        return Page(page_id, bytearray(data))
    
    def write_page(self, page: Page):
        if len(page.DATA) != self.FILE_HEADER.PAGE_SIZE:
            raise ValueError("Tamaño de página incorrecto")

        offset = self.FILE_HEADER_SIZE + page.PAGE_ID * self.FILE_HEADER.PAGE_SIZE
        with open(self.FILE_PATH, "rb+") as file:
            file.seek(offset)
            file.write(page.DATA)
        self.FILE_HEADER.N_PAGES = max(self.FILE_HEADER.N_PAGES, page.PAGE_ID + 1)

    def allocate_page(self) -> int:
        page_id = self.FILE_HEADER.N_PAGES
        self.FILE_HEADER.N_PAGES += 1
        self.write_file_header()

        return page_id

    def read_file_header(self) -> None: 
        with open(self.FILE_PATH, "rb+") as file:
            file.seek(0)
            header_data = file.read(self.FILE_HEADER_SIZE)
            header_values = struct.unpack(self.FILE_HEADER_FORMAT, header_data)
            self.FILE_HEADER = FileHeader(*header_values)
        
    def write_file_header(self) -> None:
        with open(self.FILE_PATH, "rb+") as file:
            file.seek(0)
            file.write(struct.pack(
                self.FILE_HEADER_FORMAT,
                self.FILE_HEADER.PAGE_SIZE,
                self.FILE_HEADER.ROOT_PAGE,
                self.FILE_HEADER.N_PAGES
            ))

class Rtree:
    # RTREE_FILE: RtreeFile

    #NOTE: Metodos privados
    def _load_node(self, page_id: int) -> Node:
        page = self.RTREE_FILE.read_page(page_id)
        return Node.from_page(page)

    def _save_node(self, node: Node):
        page = node.to_page(self.RTREE_FILE.FILE_HEADER.PAGE_SIZE)
        self.RTREE_FILE.write_page(page)

    def _create_node(self, is_leaf: bool) -> Node:
        page_id = self.RTREE_FILE.allocate_page()
        return Node(is_leaf, [], page_id)

    def _node_mbr(self, node: Node):
        x1 = min(e.MBR[0] for e in node.ENTRIES)
        y1 = min(e.MBR[1] for e in node.ENTRIES)
        x2 = max(e.MBR[2] for e in node.ENTRIES)
        y2 = max(e.MBR[3] for e in node.ENTRIES)

        return (x1, y1, x2, y2)

    def _area(self, mbr):
        x1, y1, x2, y2 = mbr
        return (x2 - x1) * (y2 - y1)

    def _combine(self, a, b):
        x1, y1, x2, y2 = a
        x1b, y1b, x2b, y2b = b

        return (
            min(x1, x1b),
            min(y1, y1b),
            max(x2, x2b),
            max(y2, y2b)
        )

    def _enlargement(self, mbr, new_mbr):
        combined = self._combine(mbr, new_mbr)
        return self._area(combined) - self._area(mbr)

    def _choose_leaf(self, mbr) -> Node:
        node = self._load_node(self.RTREE_FILE.FILE_HEADER.ROOT_PAGE)

        while not node.IS_LEAF:
            best_entry = None
            best_enlargement = float("inf")
            best_area = float("inf")

            for entry in node.ENTRIES:
                enlargement = self._enlargement(entry.MBR, mbr)
                area = self._area(entry.MBR)

                if (
                    enlargement < best_enlargement or
                    (enlargement == best_enlargement and area < best_area)
                ):
                    best_entry = entry
                    best_enlargement = enlargement
                    best_area = area

            node = self._load_node(best_entry.PTR[0])

        return node

    def _pick_seeds(self, entries):
        max_waste = -1
        seed1, seed2 = None, None

        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                e1 = entries[i]
                e2 = entries[j]

                combined = self._combine(e1.MBR, e2.MBR)

                waste = (
                    self._area(combined)
                    - self._area(e1.MBR)
                    - self._area(e2.MBR)
                )

                if waste > max_waste:
                    max_waste = waste
                    seed1, seed2 = e1, e2

        return seed1, seed2

    def _quadratic_split(self, node: Node, new_entry: NodeEntry):
        entries = node.ENTRIES + [new_entry]

        group1 = []
        group2 = []

        e1, e2 = self._pick_seeds(entries)

        group1.append(e1)
        group2.append(e2)

        entries.remove(e1)
        entries.remove(e2)

        m = self.RTREE_FILE.MAX_ENTRIES // 2 

        mbr1 = e1.MBR
        mbr2 = e2.MBR

        while entries:
            if len(group1) + len(entries) == m:
                group1.extend(entries)
                break

            if len(group2) + len(entries) == m:
                group2.extend(entries)
                break

            best_entry = None
            max_diff = -1

            for e in entries:
                d1 = self._enlargement(mbr1, e.MBR)
                d2 = self._enlargement(mbr2, e.MBR)
                diff = abs(d1 - d2)

                if diff > max_diff:
                    max_diff = diff
                    best_entry = e
                    best_d1 = d1
                    best_d2 = d2

            entries.remove(best_entry)

            if best_d1 < best_d2:
                group1.append(best_entry)
                mbr1 = self._combine(mbr1, best_entry.MBR)

            elif best_d2 < best_d1:
                group2.append(best_entry)
                mbr2 = self._combine(mbr2, best_entry.MBR)

            else:
                if self._area(mbr1) < self._area(mbr2):
                    group1.append(best_entry)
                    mbr1 = self._combine(mbr1, best_entry.MBR)
                else:
                    group2.append(best_entry)
                    mbr2 = self._combine(mbr2, best_entry.MBR)

        node1 = node
        node1.ENTRIES = group1

        node2 = self._create_node(node.IS_LEAF)
        node2.ENTRIES = group2

        return node1, node2
    
    def _adjust_tree(self, node: Node, split_node: Node | None):
        while True:

            if node.PARENT_ID == -1:
                if split_node:
                    new_root = self._create_node(False)

                    new_root.ENTRIES = [
                        NodeEntry(self._node_mbr(node), (node.PAGE_ID, 0)),
                        NodeEntry(self._node_mbr(split_node), (split_node.PAGE_ID, 0))
                    ]

                    node.PARENT_ID = new_root.PAGE_ID
                    split_node.PARENT_ID = new_root.PAGE_ID

                    self._save_node(node)
                    self._save_node(split_node)
                    self._save_node(new_root)

                    self.RTREE_FILE.FILE_HEADER.ROOT_PAGE = new_root.PAGE_ID
                    self.RTREE_FILE.write_file_header()

                return

            parent = self._load_node(node.PARENT_ID)

            for entry in parent.ENTRIES:
                if entry.PTR[0] == node.PAGE_ID:
                    entry.MBR = self._node_mbr(node)
                    break

            if split_node:
                new_entry = NodeEntry(
                    self._node_mbr(split_node),
                    (split_node.PAGE_ID, 0)
                )

                if len(parent.ENTRIES) < self.RTREE_FILE.MAX_ENTRIES:
                    parent.ENTRIES.append(new_entry)
                    split_node.PARENT_ID = parent.PAGE_ID
                    split_node = None
                else:
                    parent1, parent2 = self._quadratic_split(parent, new_entry)

                    parent1.PARENT_ID = parent.PARENT_ID
                    parent2.PARENT_ID = parent.PARENT_ID

                    self._save_node(parent1)
                    self._save_node(parent2)

                    node = parent1
                    split_node = parent2

            self._save_node(parent)

            node = parent

    def _overlap(self, a, b) -> bool:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b

        return not (
            ax2 < bx1 or ax1 > bx2 or
            ay2 < by1 or ay1 > by2
        )

    def _find_leaf(self, node: Node, mbr) -> Node | None:
        if node.IS_LEAF:
            for e in node.ENTRIES:
                if e.MBR == mbr:
                    return node
            return None

        for e in node.ENTRIES:
            if self._overlap(e.MBR, mbr):
                child = self._load_node(e.PTR[0])
                result = self._find_leaf(child, mbr)
                if result:
                    return result

        return None

    def _condense_tree(self, node: Node):
        Q = []

        while True:

            if node.PARENT_ID == -1:
                break

            parent = self._load_node(node.PARENT_ID)

            entry_to_remove = None
            for e in parent.ENTRIES:
                if e.PTR[0] == node.PAGE_ID:
                    entry_to_remove = e
                    break

            if len(node.ENTRIES) < self.RTREE_FILE.MAX_ENTRIES // 2:
                parent.ENTRIES.remove(entry_to_remove)

                if not node.IS_LEAF:
                    Q.extend(node.ENTRIES)
                else:
                    Q.append(node)

            else:
                entry_to_remove.MBR = self._node_mbr(node)

            self._save_node(parent)

            node = parent

        # reinsertar huérfanos
        for orphan in Q:
            if isinstance(orphan, NodeEntry):
                x1, y1, x2, y2 = orphan.MBR
                self.insert((x1, y1), orphan.PTR)
            else:
                # si es nodo completo (caso interno)
                for e in orphan.ENTRIES:
                    x1, y1, x2, y2 = e.MBR
                    self.insert((x1, y1), e.PTR)

    def _mindist(self, qx, qy, mbr) -> float:
        x1, y1, x2, y2 = mbr

        dx = 0
        if qx < x1:
            dx = x1 - qx
        elif qx > x2:
            dx = qx - x2

        dy = 0
        if qy < y1:
            dy = y1 - qy
        elif qy > y2:
            dy = qy - y2

        return (dx * dx + dy * dy) ** 0.5

    def _aux_range_search(self, node: Node, point: tuple[float, float], radio: float, result: list[tuple[tuple[float, float], tuple[int, int]]]):
        if node.IS_LEAF:
            for e in node.ENTRIES:
                x1, y1, x2, y2 = e.MBR
                px, py = x1, y1

                dist = self._mindist(point[0], point[1], e.MBR)

                if dist <= radio:
                    result.append(((px, py), e.PTR))
            return

        for e in node.ENTRIES:
            if self._mindist(point[0], point[1], e.MBR) <= radio:
                child = self._load_node(e.PTR[0])
                self._aux_range_search(child, point, radio, result)

    #NOTE: Metodos publicos
    def __init__(self):
        self.RTREE_FILE = RtreeFile()

        if self.RTREE_FILE.FILE_HEADER.ROOT_PAGE == -1:
            root = self._create_node(is_leaf=True)
            self._save_node(root)

            self.RTREE_FILE.FILE_HEADER.ROOT_PAGE = root.PAGE_ID
            self.RTREE_FILE.write_file_header()

    # NOTE
    # Este método inserta el punto recibido como argumento junto con su RID. 
    # El punto se representa como una tupla (lon, lat) y el RID como una tupla (page_id, offset).
    # Si la inserción es exitosa, se devuelve True. Si ocurre un error, se devuelve False.
    def insert(self, point: tuple[float, float], rid: tuple[int, int]) -> bool:
        try:
            mbr = (point[0], point[1], point[0], point[1])
            ptr = rid
            leaf = self._choose_leaf(mbr)
            if len(leaf.ENTRIES) < self.RTREE_FILE.MAX_ENTRIES:
                leaf.ENTRIES.append(NodeEntry(mbr, ptr))
                self._save_node(leaf)
            else:
                node1, node2 = self._quadratic_split(leaf, NodeEntry(mbr, ptr))
                self._save_node(node1)
                self._save_node(node2)
                self._adjust_tree(node1, node2)
            return True
        except:
            return False

    # NOTE
    # Este método remueve el punto recibido como argumento. Si el punto
    # no existe, se devuelve False. Si el punto existe y es removido, se 
    # devuelve True.
    def remove(self, point: tuple[float, float]) -> bool:
        mbr = (point[0], point[1], point[0], point[1])
        root = self._load_node(self.RTREE_FILE.FILE_HEADER.ROOT_PAGE)
        leaf = self._find_leaf(root, mbr)
        if leaf is None:
            return False

        leaf.ENTRIES = [
            e for e in leaf.ENTRIES
            if not (e.MBR == mbr)
        ]

        self._save_node(leaf)
        self._condense_tree(leaf)
        root = self._load_node(self.RTREE_FILE.FILE_HEADER.ROOT_PAGE)

        if not root.IS_LEAF and len(root.ENTRIES) == 1:
            child_id = root.ENTRIES[0].PTR[0]
            self.RTREE_FILE.FILE_HEADER.ROOT_PAGE = child_id
            self.RTREE_FILE.write_file_header()

        return True

    # NOTE
    # Este método usa la técnica de búsqueda en radio para hallar los vecinos 
    # circunscritos al radio. Propiamente se recibe un punto central y un valor 
    # de radio, y se devuelve una lista de puntos [(lon1, lat1), ... (lon-n, lat-n)]
    # junto con sus RIDs.
    def rangeSearch(self, point: tuple[float, float], radio: float) -> list[tuple[tuple[float, float], tuple[int, int]]]:
        result = []
        root = self._load_node(self.RTREE_FILE.FILE_HEADER.ROOT_PAGE)
        self._aux_range_search(root, point, radio, result)
        return result

    # NOTE
    # Del mismo modo que la búsqueda en rango, el método knn solicita
    # un punto y un valor k para delimitar la búsqueda de los k vecinos
    # más cercanos a un punto. La devolución está conformada por una 
    # lista de k puntos [(lon1, lat1), (lon2, lat2) ... (lon-k, lat-k)] 
    # junto con sus RIDs.
    def knnSearch(self, point: tuple[float, float], k: int) -> list[tuple[tuple[float, float], tuple[int, int]]]:
        pq = []
        result = []
        root = self._load_node(self.RTREE_FILE.FILE_HEADER.ROOT_PAGE)

        heapq.heappush(
            pq,
            (0.0, root.PAGE_ID, root)
        )

        def push_result(dist, point, rid):
            heapq.heappush(result, (-dist, point, rid))
            if len(result) > k:
                heapq.heappop(result)

        while pq:
            dist_node, _, node = heapq.heappop(pq)

            if result and dist_node > -result[0][0]:
                continue

            if node.IS_LEAF:

                for e in node.ENTRIES:
                    px, py = e.MBR[0], e.MBR[1]

                    dx = point[0] - px
                    dy = point[1] - py
                    dist = (dx*dx + dy*dy) ** 0.5

                    push_result(dist, (px, py), e.PTR)

            else:

                children = []

                for e in node.ENTRIES:
                    child_id = e.PTR[0]
                    child = self._load_node(child_id)

                    dist = self._mindist(point[0], point[1], e.MBR)

                    children.append((dist, child))

                for item in children:
                    heapq.heappush(pq, (item[0], item[1].PAGE_ID, item[1]))

        final = []
        while result:
            dist, pt, rid = heapq.heappop(result)
            final.append((pt, rid))

        return final[::-1]

    # NOTE: 
    # Este método crea la visualización gráfica del R-tree con matplolib
    # el gráfico se deposita directamente en la dirección de la variable 
    # glboal GRAPH_DIR y la función devuelve su path como string.
    def visualize(self) -> str:
        fig, ax = plt.subplots()
        root = self._load_node(self.RTREE_FILE.FILE_HEADER.ROOT_PAGE)

        def draw_node(node: Node, depth=0):
            color = "blue" if node.IS_LEAF else "red"

            for e in node.ENTRIES:
                x1, y1, x2, y2 = e.MBR

                # MBR
                ax.plot(
                    [x1, x2, x2, x1, x1],
                    [y1, y1, y2, y2, y1],
                    color=color,
                    linewidth=max(1.0, 2.0 - depth * 0.3),
                    alpha=0.6
                )

                if not node.IS_LEAF:
                    child = self._load_node(e.PTR[0])
                    draw_node(child, depth + 1)

        draw_node(root)

        ax.set_title("R-Tree Gráfico")
        ax.set_aspect("equal")
        ax.grid(True)

        path = os.path.join(GRAPH_DIR, "rtree.png")
        os.makedirs(GRAPH_DIR, exist_ok=True)

        plt.savefig(path, dpi=200, bbox_inches="tight")
        plt.close()

        return path

if __name__ == "__main__":
    rtree = Rtree()

    point = np.array([1,8])
    print(point)
    rtree.insert(point, [1, "sdad"])