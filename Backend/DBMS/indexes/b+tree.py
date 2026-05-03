import struct
from dataclasses import dataclass, field
from typing import List, Tuple

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

@dataclass
class LeafNode(BPlusNode):
    values: List[Tuple[int, int]] = field(default_factory=list)  # Representa (PageID, SlotID)
    next_leaf: int = -1

@dataclass
class InternalNode(BPlusNode):
    children: List[int] = field(default_factory=list)