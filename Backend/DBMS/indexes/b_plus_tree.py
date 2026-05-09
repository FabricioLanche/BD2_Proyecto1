import struct
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Any
from bisect import bisect_right, bisect_left
from Backend.DBMS.config import get_index_page_size

@dataclass
class BPlusHeader:
    root_page_id: int = -1
    height: int = 0

    FORMAT = '<ii'
    SIZE = struct.calcsize(FORMAT)

    def to_bytes(self) -> bytes:
        return struct.pack(self.FORMAT, self.root_page_id, self.height)

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
    keys: List[Any] = field(default_factory=list)

@dataclass
class LeafNode(BPlusNode):
    values: List[Tuple[int, int]] = field(default_factory=list)
    next_leaf: int = -1

@dataclass
class InternalNode(BPlusNode):
    children: List[int] = field(default_factory=list)


class BPlusTree:
    def __init__(self, filename: str, page_manager, key_format: str = 'i'):
        self.pm = page_manager
        self.PAGE_SIZE = getattr(self.pm, 'PAGE_SIZE', get_index_page_size())
        self.key_format = key_format
        self.key_size   = struct.calcsize(key_format)
        self.key_is_str = key_format.endswith('s')
        self.header = self._load_or_init_header()
        (self.max_keys_leaf, self.max_values_leaf,
        self.max_keys_internal, self.max_children_internal) = self._compute_capacity()
        self.min_keys_leaf     = self._min_keys(self.max_keys_leaf)
        self.min_keys_internal = self._min_keys(self.max_keys_internal)

    def _encode_key(self, key) -> bytes:
        if self.key_is_str:
            encoded = key.encode('utf-8')
            if len(encoded) > self.key_size:
                raise ValueError(
                    f"Llave '{key}' demasiado grande ({len(encoded)} bytes). "
                    f"Máximo: {self.key_size}")
            return encoded.ljust(self.key_size, b'\x00')
        return struct.pack(self.key_format, key)

    def _decode_key(self, raw: bytes):
        if self.key_is_str:
            return raw.decode('utf-8').rstrip('\x00')
        return struct.unpack(self.key_format, raw)[0]

    @staticmethod
    def _min_keys(max_keys: int) -> int:
        import math
        return math.ceil(max_keys / 2) - 1

    def _compute_capacity(self):
        OVERHEAD = NodeHeader.SIZE + 4
        usable   = self.PAGE_SIZE - OVERHEAD

        leaf_entry          = self.key_size + 8
        max_keys_leaf       = usable // leaf_entry
        max_values_leaf     = max_keys_leaf

        internal_entry        = self.key_size + 4
        max_keys_internal     = usable // internal_entry
        max_children_internal = max_keys_internal + 1

        return max_keys_leaf, max_values_leaf, max_keys_internal, max_children_internal

    def serialize_node(self, node: BPlusNode) -> bytes:
        buffer = bytearray(self.PAGE_SIZE)

        if node.header.is_leaf:
            assert node.header.num_keys == len(node.keys)
            assert len(node.values) == len(node.keys)
        else:
            assert node.header.num_keys == len(node.keys)
            assert len(node.children) == len(node.keys) + 1

        buffer[:NodeHeader.SIZE] = node.header.to_bytes()
        offset = NodeHeader.SIZE

        if node.header.is_leaf:
            node: LeafNode
            struct.pack_into('<i', buffer, offset, node.next_leaf)
            offset += 4
            for i in range(node.header.num_keys):
                if offset + self.key_size + 8 > self.PAGE_SIZE:
                    raise ValueError("Leaf overflow during serialization")
                buffer[offset:offset + self.key_size] = self._encode_key(node.keys[i])
                offset += self.key_size
                struct.pack_into('<ii', buffer, offset, *node.values[i])
                offset += 8
        else:
            node: InternalNode
            if len(node.children) == 0:
                raise ValueError("Internal node without children")
            struct.pack_into('<i', buffer, offset, node.children[0])
            offset += 4
            for i in range(node.header.num_keys):
                if offset + self.key_size + 4 > self.PAGE_SIZE:
                    raise ValueError("Internal overflow during serialization")
                buffer[offset:offset + self.key_size] = self._encode_key(node.keys[i])
                offset += self.key_size
                struct.pack_into('<i', buffer, offset, node.children[i + 1])
                offset += 4

        return bytes(buffer)

    def deserialize_node(self, data: bytes) -> BPlusNode:
        header = NodeHeader.from_bytes(data[:NodeHeader.SIZE])

        if header.is_leaf:
            if header.num_keys > self.max_keys_leaf:
                raise ValueError("Corrupted leaf node (too many keys)")
        else:
            if header.num_keys > self.max_keys_internal:
                raise ValueError("Corrupted internal node (too many keys)")

        offset = NodeHeader.SIZE

        if header.is_leaf:
            node = LeafNode(header=header)
            node.next_leaf = struct.unpack_from('<i', data, offset)[0]
            offset += 4
            for _ in range(header.num_keys):
                key = self._decode_key(data[offset:offset + self.key_size])
                offset += self.key_size
                page_id, slot = struct.unpack_from('<ii', data, offset)
                offset += 8
                node.keys.append(key)
                node.values.append((page_id, slot))
        else:
            node = InternalNode(header=header)
            node.children.append(struct.unpack_from('<i', data, offset)[0])
            offset += 4
            for _ in range(header.num_keys):
                key = self._decode_key(data[offset:offset + self.key_size])
                offset += self.key_size
                child = struct.unpack_from('<i', data, offset)[0]
                offset += 4
                node.keys.append(key)
                node.children.append(child)

        return node
    
    def _load_or_init_header(self):
        data   = self.pm.read_page(0)
        header = BPlusHeader.from_bytes(data)
        if header.root_page_id < 1:
            header.root_page_id = -1
            self._save_header(header)
        return header

    def _save_header(self, header=None):
        h    = header or self.header
        page = bytearray(self.pm.read_page(0))
        page[:BPlusHeader.SIZE] = h.to_bytes()
        self.pm.write_page(0, bytes(page))

    def _read_node(self, page_id: int) -> BPlusNode:
        return self.deserialize_node(self.pm.read_page(page_id))

    def _write_node(self, page_id: int, node: BPlusNode):
        node.header.num_keys = len(node.keys)
        if node.header.is_leaf:
            assert len(node.values) == len(node.keys)
        else:
            if len(node.keys) > 0 or len(node.children) > 0:
                assert len(node.children) == len(node.keys) + 1, \
                    f"Internal node inválido: {len(node.keys)} keys, {len(node.children)} children"
        self.pm.write_page(page_id, self.serialize_node(node))

    def _new_node(self, is_leaf: bool, parent_id: int = -1):
        page_id = self.pm.allocate_new_page()
        header  = NodeHeader(is_leaf, 0, parent_id)
        node    = LeafNode(header) if is_leaf else InternalNode(header)
        return page_id, node

    def _update_parent_pointer(self, page_id: int, new_parent_id: int):
        raw = bytearray(self.pm.read_page(page_id))
        struct.pack_into('<i', raw, NodeHeader.SIZE - 4, new_parent_id)
        self.pm.write_page(page_id, bytes(raw))

    def _set_parent_in_node(self, node: BPlusNode, new_parent_id: int):
        node.header.parent = new_parent_id

    # SEARCH
    def _find_leaf(self, key) -> Tuple[int, LeafNode]:
        if self.header.root_page_id == -1:
            raise ValueError("Empty tree")
        page = self.header.root_page_id
        node = self._read_node(page)
        while not node.header.is_leaf:
            i    = bisect_right(node.keys, key)
            page = node.children[i]
            node = self._read_node(page)
        return page, node
    
    def search(self, key):
        try:
            current_id, node = self._find_leaf(key)
            results = []
            while current_id != -1:
                idx = bisect_left(node.keys, key)
                while idx < len(node.keys) and node.keys[idx] == key:
                    results.append(node.values[idx])
                    idx += 1
                if idx >= len(node.keys):
                    current_id = node.next_leaf
                    if current_id != -1:
                        node = self._read_node(current_id)
                else:
                    break
            return results if results else None
        except ValueError:
            return None

    def range_search(self, start_key, end_key):
        if self.header.root_page_id == -1:
            return []
        results = []
        current_page_id, node = self._find_leaf(start_key)
        while current_page_id != -1:
            idx = bisect_left(node.keys, start_key)
            for i in range(idx, len(node.keys)):
                if node.keys[i] > end_key:
                    return results
                results.append((node.keys[i], node.values[i]))
            current_page_id = node.next_leaf
            if current_page_id != -1:
                node = self._read_node(current_page_id)
        return results
    
    # INSERT
    def insert(self, key, value: Tuple[int, int]):
        if self.header.root_page_id == -1:
            page_id, node = self._new_node(is_leaf=True)
            node.keys   = [key]
            node.values = [value]
            self.header.root_page_id = page_id
            self.header.height       = 1
            self._write_node(page_id, node)
            self._save_header()
            return

        leaf_id, node = self._find_leaf(key)
        idx = bisect_right(node.keys, key)
        node.keys.insert(idx, key)
        node.values.insert(idx, value)

        if len(node.keys) <= self.max_keys_leaf:
            self._write_node(leaf_id, node)
        else:
            self._split_leaf(leaf_id, node)

    def _split_leaf(self, left_id: int, left_node: LeafNode):
        parent_id = left_node.header.parent

        new_page_id, new_node = self._new_node(is_leaf=True, parent_id=parent_id)

        mid = len(left_node.keys) // 2
        new_node.keys    = left_node.keys[mid:]
        new_node.values  = left_node.values[mid:]
        left_node.keys   = left_node.keys[:mid]
        left_node.values = left_node.values[:mid]

        new_node.next_leaf  = left_node.next_leaf
        left_node.next_leaf = new_page_id
        split_key           = new_node.keys[0]

        self._write_node(left_id,   left_node)
        self._write_node(new_page_id, new_node)
        self._insert_into_parent(left_id, split_key, new_page_id, parent_id)

    def _insert_into_parent(self, left_id: int, key, right_id: int, parent_id: int):
        if parent_id == -1:
            new_root_id, new_root = self._new_node(is_leaf=False)
            new_root.keys     = [key]
            new_root.children = [left_id, right_id]

            self.header.root_page_id = new_root_id
            self.header.height      += 1
            self._save_header()

            self._update_parent_pointer(left_id,  new_root_id)
            self._update_parent_pointer(right_id, new_root_id)
            self._write_node(new_root_id, new_root)
            return

        parent = self._read_node(parent_id)
        idx    = bisect_right(parent.keys, key)
        parent.keys.insert(idx, key)
        parent.children.insert(idx + 1, right_id)

        if len(parent.keys) <= self.max_keys_internal:
            self._write_node(parent_id, parent)
        else:
            self._split_internal(parent_id, parent)

    def _split_internal(self, old_id: int, old_node: InternalNode):
        parent_id = old_node.header.parent

        new_id, new_node = self._new_node(is_leaf=False, parent_id=parent_id)

        mid       = len(old_node.keys) // 2
        split_key = old_node.keys[mid]

        new_node.keys     = old_node.keys[mid + 1:]
        new_node.children = old_node.children[mid + 1:]
        old_node.keys     = old_node.keys[:mid]
        old_node.children = old_node.children[:mid + 1]

        self._write_node(old_id, old_node)
        self._write_node(new_id, new_node)

        for child_id in new_node.children:
            self._update_parent_pointer(child_id, new_id)

        self._insert_into_parent(old_id, split_key, new_id, parent_id)

    # REMOVE 
    def remove(self, key, value: Optional[Tuple[int, int]] = None) -> bool:
        if self.header.root_page_id == -1:
            return False

        try:
            leaf_id, leaf = self._find_leaf(key)
        except ValueError:
            return False

        idx     = bisect_left(leaf.keys, key)
        deleted = False
        while idx < len(leaf.keys) and leaf.keys[idx] == key:
            if value is None or leaf.values[idx] == value:
                leaf.keys.pop(idx)
                leaf.values.pop(idx)
                deleted = True
                break
            idx += 1

        if not deleted:
            return False

        if leaf.header.parent == -1:
            self._write_node(leaf_id, leaf)
            if len(leaf.keys) == 0:
                self.header.root_page_id = -1
                self.header.height       = 0
                self._save_header()
            return True

        self._write_node(leaf_id, leaf)

        if len(leaf.keys) < self.min_keys_leaf:
            self._fix_leaf_underflow(leaf_id, leaf)

        return True

    def _child_position(self, parent: InternalNode, child_id: int) -> int:
        children = parent.children
        n = len(children)
        
        if children[0] == child_id:
            return 0
        if children[-1] == child_id:
            return n - 1
        
        return children.index(child_id)

    def _fix_leaf_underflow(self, leaf_id: int, leaf: LeafNode):
        parent_id = leaf.header.parent
        parent    = self._read_node(parent_id)
        pos       = self._child_position(parent, leaf_id) 

        if pos > 0:
            left_sib_id = parent.children[pos - 1]
            left_sib    = self._read_node(left_sib_id)
            if len(left_sib.keys) > self.min_keys_leaf:
                self._borrow_leaf_from_left(leaf_id, leaf, left_sib_id, left_sib, parent, parent_id, pos)
                return

        if pos < len(parent.children) - 1:
            right_sib_id = parent.children[pos + 1]
            right_sib    = self._read_node(right_sib_id)
            if len(right_sib.keys) > self.min_keys_leaf:
                self._borrow_leaf_from_right(leaf_id, leaf, right_sib_id, right_sib, parent, parent_id, pos)
                return

        if pos > 0:
            self._merge_leaves(parent.children[pos - 1], leaf_id, parent, parent_id, pos)
        else:
            self._merge_leaves(leaf_id, parent.children[pos + 1], parent, parent_id, pos + 1)

    def _borrow_leaf_from_left(self, leaf_id, leaf: LeafNode, left_id, left: LeafNode, parent: InternalNode, parent_id: int, pos: int):
        leaf.keys.insert(0,   left.keys.pop())
        leaf.values.insert(0, left.values.pop())
        parent.keys[pos - 1] = leaf.keys[0]
        self._write_node(left_id,   left)
        self._write_node(leaf_id,   leaf)
        self._write_node(parent_id, parent)

    def _borrow_leaf_from_right(self, leaf_id, leaf: LeafNode, right_id, right: LeafNode, parent: InternalNode, parent_id: int, pos: int):
        leaf.keys.append(right.keys.pop(0))
        leaf.values.append(right.values.pop(0))
        parent.keys[pos] = right.keys[0]
        self._write_node(right_id,  right)
        self._write_node(leaf_id,   leaf)
        self._write_node(parent_id, parent)

    def _merge_leaves(self, left_id: int, right_id: int, parent: InternalNode, parent_id: int, right_pos: int):
        left  = self._read_node(left_id)
        right = self._read_node(right_id)

        left.keys.extend(right.keys)
        left.values.extend(right.values)
        left.next_leaf = right.next_leaf

        sep_idx = right_pos - 1
        parent.keys.pop(sep_idx)
        parent.children.pop(right_pos)

        self._write_node(left_id,   left)
        self._write_node(parent_id, parent)

        if parent_id == self.header.root_page_id:
            self._shrink_root_if_needed(parent_id, parent)
        elif len(parent.keys) < self.min_keys_internal:
            self._fix_internal_underflow(parent_id, parent)

    def _fix_internal_underflow(self, node_id: int, node: InternalNode):
        parent_id = node.header.parent
        if parent_id == -1:
            self._shrink_root_if_needed(node_id, node)
            return

        parent = self._read_node(parent_id)
        pos    = self._child_position(parent, node_id)
        if pos > 0:
            left_sib_id = parent.children[pos - 1]
            left_sib    = self._read_node(left_sib_id)
            if len(left_sib.keys) > self.min_keys_internal:
                self._borrow_internal_from_left(node_id, node, left_sib_id, left_sib, parent, parent_id, pos)
                return

        if pos < len(parent.children) - 1:
            right_sib_id = parent.children[pos + 1]
            right_sib    = self._read_node(right_sib_id)
            if len(right_sib.keys) > self.min_keys_internal:
                self._borrow_internal_from_right(node_id, node, right_sib_id, right_sib, parent, parent_id, pos)
                return

        if pos > 0:
            self._merge_internal(parent.children[pos - 1], node_id, parent, parent_id, pos)
        else:
            self._merge_internal(node_id, parent.children[pos + 1], parent, parent_id, pos + 1)

    def _borrow_internal_from_left(self, node_id, node: InternalNode, left_id, left: InternalNode, parent: InternalNode, parent_id: int, pos: int):
        sep_idx = pos - 1
        node.keys.insert(0, parent.keys[sep_idx])
        moved_child = left.children.pop()
        node.children.insert(0, moved_child)
        self._update_parent_pointer(moved_child, node_id)
        parent.keys[sep_idx] = left.keys.pop()
        self._write_node(left_id,   left)
        self._write_node(node_id,   node)
        self._write_node(parent_id, parent)

    def _borrow_internal_from_right(self, node_id, node: InternalNode, right_id, right: InternalNode, parent: InternalNode, parent_id: int, pos: int):
        sep_idx = pos
        node.keys.append(parent.keys[sep_idx])
        moved_child = right.children.pop(0)
        node.children.append(moved_child)
        self._update_parent_pointer(moved_child, node_id)
        parent.keys[sep_idx] = right.keys.pop(0)
        self._write_node(right_id,  right)
        self._write_node(node_id,   node)
        self._write_node(parent_id, parent)

    def _merge_internal(self, left_id: int, right_id: int, parent: InternalNode, parent_id: int, right_pos: int):
        left  = self._read_node(left_id)
        right = self._read_node(right_id)

        sep_idx = right_pos - 1
        sep_key = parent.keys.pop(sep_idx)
        parent.children.pop(right_pos)

        left.keys.append(sep_key)
        left.keys.extend(right.keys)
        left.children.extend(right.children)

        for child_id in right.children:
            self._update_parent_pointer(child_id, left_id)

        self._write_node(left_id,   left)
        self._write_node(parent_id, parent)

        if parent_id == self.header.root_page_id:
            self._shrink_root_if_needed(parent_id, parent)
        elif len(parent.keys) < self.min_keys_internal:
            self._fix_internal_underflow(parent_id, parent)

    def _shrink_root_if_needed(self, root_id: int, root: InternalNode):
        if not root.header.is_leaf and len(root.keys) == 0:
            new_root_id              = root.children[0]
            self.header.root_page_id = new_root_id
            self.header.height      -= 1
            self._save_header()
            self._update_parent_pointer(new_root_id, -1)

    def flush_metadata(self) -> None:
        self._save_header()