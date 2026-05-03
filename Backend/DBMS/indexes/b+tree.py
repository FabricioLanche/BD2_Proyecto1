import struct
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
#from organization.page_manager import PageManager

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
        
        # Serializar claves
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
        # Serializar Values (RID: PageID, SlotID)
        for p, s in self.values:
            struct.pack_into('<ii', data, offset, p, s)
            offset += 8
        # Serializar puntero a siguiente hoja
        struct.pack_into('<i', data, offset, self.next_leaf)
        return bytes(data)

@dataclass
class InternalNode(BPlusNode):
    children: List[int] = field(default_factory=list)

    def to_bytes(self, page_size: int) -> bytes:
        data, offset = super().serialize(page_size)
        # Serializar hijos (siempre hay num_keys + 1)
        for c in self.children:
            struct.pack_into('<i', data, offset, c)
            offset += 4
        return bytes(data)
