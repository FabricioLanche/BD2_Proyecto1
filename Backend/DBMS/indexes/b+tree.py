import struct
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from organization.page_manager import PageManager
from bisect import bisect_left #busqueda binaria

@dataclass
class BPlusHeader:
    root_page_id: int = -1
    height: int = 0
    order: int = 4
    
    FORMAT = '<iii'
    SIZE = struct.calcsize(FORMAT)

    def to_bytes(self) -> bytes:
        return struct.pack(self.FORMAT, self.root_page_id, self.height, self.order)

    @classmethod
    def from_bytes(cls, data: bytes):
        return cls(*struct.unpack(cls.FORMAT, data[:cls.SIZE]))

@dataclass
class NodeHeader:
    is_leaf: bool
    num_keys: int
    parent: int
    
    FORMAT = '<?ii'
    SIZE = struct.calcsize(FORMAT)

    def to_bytes(self) -> bytes:
        return struct.pack(self.FORMAT, self.is_leaf, self.num_keys, self.parent)

    @classmethod
    def from_bytes(cls, data: bytes):
        return cls(*struct.unpack(cls.FORMAT, data[:cls.SIZE]))

@dataclass
class BPlusNode:
    header: NodeHeader
    keys: List[int] = field(default_factory=list)

    def serialize(self, page_size: int) -> bytes:
        data = bytearray(page_size)
        data[:NodeHeader.SIZE] = self.header.to_bytes()
        offset = NodeHeader.SIZE
        
        # Serializacion
        for k in self.keys:
            struct.pack_into('<i', data, offset, k)
            offset += 4
        return data, offset

@dataclass
class LeafNode(BPlusNode):
    values: List[Tuple[int, int]] = field(default_factory=list)
    next_leaf: int = -1

    def to_bytes(self, page_size: int) -> bytes:
        data, offset = super().serialize(page_size)
        # Serializacion RID
        for p, s in self.values:
            struct.pack_into('<ii', data, offset, p, s)
            offset += 8
        # Serializacion next_leaf
        struct.pack_into('<i', data, offset, self.next_leaf)
        return bytes(data)

@dataclass
class InternalNode(BPlusNode):
    children: List[int] = field(default_factory=list)

    def to_bytes(self, page_size: int) -> bytes:
        data, offset = super().serialize(page_size)
        # Serializacion hijos 
        for c in self.children:
            struct.pack_into('<i', data, offset, c)
            offset += 4
        return bytes(data)
    

class BPlusTree:
    def __init__(self, filename: str, page_manager: Optional[PageManager] = None):
        self.pm = page_manager or PageManager(filename)
        self.header = self._load_or_init_header()
        self.max_keys = self.header.order - 1

    def _load_or_init_header(self) -> BPlusHeader:
        raw_data = self.pm.read_page(0)
        # Si la página está vacía
        if raw_data[:4] == b'\x00\x00\x00\x00':
            header = BPlusHeader()
            self._save_header(header)
            return header
        return BPlusHeader.from_bytes(raw_data)

    def _save_header(self, header: Optional[BPlusHeader] = None):
        h = header or self.header
        page_data = bytearray(self.pm.read_page(0))
        page_data[:BPlusHeader.SIZE] = h.to_bytes()
        self.pm.write_page(0, bytes(page_data))

    # Métodos read/write nodes
    def _read_node(self, page_id: int) -> BPlusNode:
        data = self.pm.read_page(page_id)
        header = NodeHeader.from_bytes(data)
        offset = NodeHeader.SIZE

        # Reconstruir claves comunes
        keys = [struct.unpack_from('<i', data, offset + i*4)[0] 
                for i in range(header.num_keys)]
        offset += (header.num_keys * 4)

        if header.is_leaf:
            # Reconstruir valores y next_leaf
            values = [struct.unpack_from('<ii', data, offset + i*8) 
                    for i in range(header.num_keys)]
            offset += (header.num_keys * 8)
            next_leaf = struct.unpack_from('<i', data, offset)[0]
            return LeafNode(header, keys, values, next_leaf)
        
        else:
            # Reconstruir hijos
            children = [struct.unpack_from('<i', data, offset + i*4)[0] 
                        for i in range(header.num_keys + 1)]
            return InternalNode(header, keys, children)

    def _write_node(self, page_id: int, node: BPlusNode):
        self.pm.write_page(page_id, node.to_bytes(self.pm.PAGE_SIZE))

    def _new_node(self, is_leaf: bool) -> Tuple[int, BPlusNode]:
        page_id = self.pm.allocate_new_page()
        header = NodeHeader(is_leaf=is_leaf, num_keys=0, parent=-1)
        node = LeafNode(header) if is_leaf else InternalNode(header)
        return page_id, node
    
    # Búsqueda y recorrido
    def _find_leaf(self, key: int) -> Tuple[int, LeafNode]:
        current_page_id = self.header.root_page_id
        node = self._read_node(current_page_id)

        while not node.header.is_leaf:
            i = bisect_left(node.keys, key)
            
            # Si la llave es igual a una en el nodo interno, vamos al hijo derecho (i+1)
            # pero bisect_left con >= nos da el índice exacto para B+
            if i < len(node.keys) and key == node.keys[i]:
                next_page = node.children[i + 1]
            else:
                next_page = node.children[i]
            
            current_page_id = next_page
            node = self._read_node(current_page_id)

        return current_page_id, node

    def search(self, key: int) -> Optional[Tuple[int, int]]:
        if self.header.root_page_id == -1:
            return None
        
        _, leaf = self._find_leaf(key)
        
        i = bisect_left(leaf.keys, key)
        if i < len(leaf.keys) and leaf.keys[i] == key:
            return leaf.values[i]
        return None 
    
    # Busqueda por rango
    def range_search(self, start_key: int, end_key: int) -> List[Tuple[int, int]]:
        results = []
        if self.header.root_page_id == -1:
            return results
        
        current_page_id, leaf = self._find_leaf(start_key)

        while True:
            idx = bisect_left(leaf.keys, start_key)
            
            for i in range(idx, len(leaf.keys)):
                if leaf.keys[i] > end_key:
                    return results
                results.append(leaf.values[i])

            if leaf.next_leaf == -1:
                break

            # Moverse a la siguiente página física (Lado Físico)
            current_page_id = leaf.next_leaf
            leaf = self._read_node(current_page_id)

        return results