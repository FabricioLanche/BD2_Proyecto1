import struct
import csv
import operator
import re
from typing import List, Tuple, Optional, Any
from .page_manager import PageManager
from .data_structures import TableConfig, Record
from Backend.DBMS.utils.path_utils import resolve_data_path


class HeapFile:
    # Formato de la página 0 (metadata)
    # first_free_rid_page (int32), first_free_rid_slot (int32), last_page_id (int32), total_records (int32)
    _METADATA_FORMAT = '<iiii'
    _METADATA_SIZE = struct.calcsize(_METADATA_FORMAT)
    
    # Formato de la cabecera de página de datos: record_count (int16)
    _PAGE_HEADER_FORMAT = '<H'
    _PAGE_HEADER_SIZE = struct.calcsize(_PAGE_HEADER_FORMAT)
    
    def __init__(self, filename: str, config: TableConfig, page_manager: Optional[PageManager] = None):
        self.filename = resolve_data_path(filename, create_parent=True)
        self.config = config
        self.pm = page_manager or PageManager(self.filename)
        
        # Calcula cuántos registros caben por página
        usable_space = self.pm.PAGE_SIZE - self._PAGE_HEADER_SIZE
        self.records_per_page = usable_space // config.get_data_size()
        
        # Inicializa o carga metadata de la página 0
        self._init_metadata()
    
    def _init_metadata(self) -> None:
        page0 = self.pm.read_page(0)
        
        if page0[:self._METADATA_SIZE] == b'\x00' * self._METADATA_SIZE:
            self.first_free_rid = (-1, -1)  # Sin huecos inicialmente
            self.last_page_id = 0
            self.total_records = 0 # Total de registros activos
            self._persist_metadata()
        else:
            # Cargar metadata existente
            data = struct.unpack(self._METADATA_FORMAT, page0[:self._METADATA_SIZE])
            self.first_free_rid = (data[0], data[1])
            self.last_page_id = data[2]
            self.total_records = data[3]
    
    def _persist_metadata(self) -> None:
        # Guarda la metadata en la página 0 usando PageManager
        # Solo llamar en momentos clave (flush, init)
        page0 = bytearray(self.pm.read_page(0))
        metadata = struct.pack(
            self._METADATA_FORMAT,
            self.first_free_rid[0],  # page_id 
            self.first_free_rid[1],  # slot_id 
            self.last_page_id,
            self.total_records
        )
        page0[:self._METADATA_SIZE] = metadata
        self.pm.write_page(0, bytes(page0))
    
    def flush_metadata(self) -> None:
        self._persist_metadata()
    
    def insert(self, record: Record) -> Tuple[int, int]:
        record_bytes = record.to_bytes(self.config)
        
        # Caso 1: Hay "huecos" disponibles
        if self.first_free_rid != (-1, -1):
            page_id, slot_id = self.first_free_rid
            page = bytearray(self.pm.read_page(page_id))
            
            slot_offset = self._slot_offset(slot_id)

            # El hueco almacena el siguiente RID disponible en sus primeros 8 bytes
            if len(page) >= slot_offset + 8:
                next_page, next_slot = struct.unpack('<ii', page[slot_offset:slot_offset+8])
                self.first_free_rid = (next_page, next_slot)
            else:
                self.first_free_rid = (-1, -1)
            self.total_records += 1

            self._write_record_to_slot(page, slot_id, record_bytes)
            self.pm.write_page(page_id, bytes(page))
            return (page_id, slot_id)
        
        # Caso 2: No hay huecos
        page_id = self.last_page_id
        page = bytearray(self.pm.read_page(page_id))
        record_count = self._read_page_header(page)
        
        # Si la página actual está llena, asigna una nueva
        if record_count >= self.records_per_page:
            page_id = self.pm.allocate_new_page()
            self.last_page_id = page_id
            page = bytearray(self.pm.read_page(page_id))  # Leer desde PM
            record_count = self._read_page_header(page)   # Obtener count real
        
        slot_id = record_count
        self._write_record_to_slot(page, slot_id, record_bytes)
        record_count += 1
        self._write_page_header(page, record_count)
        
        self.pm.write_page(page_id, bytes(page))
        self.total_records += 1        
        return (page_id, slot_id)
    
    def search(self, rid: Tuple[int, int]) -> Optional[Record]:
        page_id, slot_id = rid
        page = self.pm.read_page(page_id)
        record_count = self._read_page_header(page)
        
        if slot_id >= record_count:
            return None # Slot fuera de rango -> No existe el registro
        
        record_bytes = self._read_record_from_slot(page, slot_id)
        data_tuple = struct.unpack(self.config.data_format, record_bytes)
        return Record(data_tuple, self.config)
    
    #Busqueda por rango tras obtener lista de RIDs de los indices
    def get_batch(self, rid_list: List[Tuple[int, int]]) -> List[Record]:
        if not rid_list:
            return []
        
        # Agrupar por page_id
        by_page = {}
        for page_id, slot_id in rid_list:
            if page_id not in by_page:
                by_page[page_id] = []
            by_page[page_id].append(slot_id)
        
        # Ordenar páginas para lectura secuencial
        sorted_pages = sorted(by_page.keys())
        
        records = []
        for page_id in sorted_pages:
            page = self.pm.read_page(page_id)
            for slot_id in by_page[page_id]:
                record_bytes = self._read_record_from_slot(page, slot_id)
                data_tuple = struct.unpack(self.config.data_format, record_bytes)
                records.append(Record(data_tuple, self.config))
        
        return records

    def filter_records(self, column_name: str, operator_str: str, value: Any) -> List[Record]:
        deleted_rids = self._get_deleted_rids()
        
        operator_str = operator_str.upper() if isinstance(operator_str, str) else operator_str
        
        ops = {
            '=': operator.eq,
            '==': operator.eq,
            '!=': operator.ne,
            '>': operator.gt,
            '>=': operator.ge,
            '<': operator.lt,
            '<=': operator.le,
            'BETWEEN': lambda val, limits: limits[0] <= val <= limits[1]
        }
        
        op_func = ops.get(operator_str)
        if not op_func:
            raise ValueError(f"Operador no soportado: {operator_str}")
            
        if operator_str == 'BETWEEN' and (not isinstance(value, (list, tuple)) or len(value) != 2):
            raise ValueError("Para el operador BETWEEN, 'value' debe ser una tupla o lista de dos elementos (v1, v2)")
            
        results = []
        for page_id in range(1, self.last_page_id + 1):
            try:
                page = self.pm.read_page(page_id)
            except Exception:
                continue
                
            record_count = self._read_page_header(page)
            for slot_id in range(record_count):
                # Ignora los RIDs eliminados
                if (page_id, slot_id) in deleted_rids:
                    continue
                
                record_bytes = self._read_record_from_slot(page, slot_id)
                data_tuple = struct.unpack(self.config.data_format, record_bytes)
                record = Record(data_tuple, self.config)
                
                record_val = record.get_attribute(column_name)
                
                # Manejar comparaciones de strings con padding
                if isinstance(record_val, str):
                    record_val = record_val.strip()
                
                if op_func(record_val, value):
                    results.append(record)
                    
        return results


    def exists_pk(self, value: Any) -> Optional[Tuple[int, int]]:
        # Busca si existe un registro cuya PK sea igual a `value`.
        search_value = value.strip() if isinstance(value, str) else value
        deleted_rids  = self._get_deleted_rids()

        for page_id in range(1, self.last_page_id + 1):
            try:
                page = self.pm.read_page(page_id)
            except Exception:
                continue

            record_count = self._read_page_header(page)
            for slot_id in range(record_count):
                if (page_id, slot_id) in deleted_rids:
                    continue

                record_val = self._read_pk_from_slot(page, slot_id)
                if isinstance(record_val, str):
                    record_val = record_val.strip()

                if record_val == search_value:
                    return (page_id, slot_id)

        return None
    def delete(self, rid: Tuple[int, int]) -> bool:
        page_id, slot_id = rid
        page = bytearray(self.pm.read_page(page_id))
        record_count = self._read_page_header(page)
        
        if slot_id >= record_count:
            return False # Slot fuera de rango -> No existe el registro
        
        # Guarda el RID actual del first_free_rid en los primeros 8 bytes
        next_rid_bytes = struct.pack('<ii', self.first_free_rid[0], self.first_free_rid[1])
        
        slot_offset = self._slot_offset(slot_id)
        page[slot_offset:slot_offset + 8] = next_rid_bytes
        
        self.first_free_rid = (page_id, slot_id)
        
        self.pm.write_page(page_id, bytes(page))
        self.total_records = max(0, self.total_records - 1)
        return True
    
    def load_from_csv_optimized(self, csv_path: str) -> List[Tuple[Tuple[int, int], Tuple]]:
        # Carga desde un archivo csv a un formato binario - > retorna 
        # una lista de (RID, data_tuple)
        results = []
        
        # Orden de columnas según column_map
        col_order = sorted(self.config.column_map.items(), key=lambda x: x[1])
        col_names = [name for name, _ in col_order]
        
        current_page_id = self.last_page_id + 1 if self.last_page_id > 0 else 1
        current_page = bytearray(b'\x00' * self.pm.PAGE_SIZE)
        current_record_count = 0
        
        record_size = self.config.get_data_size()
        record_count = 0
        
        conversions = [self.config.get_column_format(name) for name in col_names]
        
        with open(csv_path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                values = []
                for col_name, col_fmt in zip(col_names, conversions):
                    raw = row[col_name].strip()
                    values.append(self._cast_value(raw, col_fmt))
                
                data_tuple = tuple(values)
                record = Record(data_tuple, self.config)
                record_bytes = record.to_bytes(self.config)
                
                if current_record_count >= self.records_per_page:
                    self._write_page_header(current_page, current_record_count)
                    self.pm.write_page(current_page_id, bytes(current_page))
                    current_page_id += 1
                    current_page = bytearray(b'\x00' * self.pm.PAGE_SIZE)
                    current_record_count = 0
                
                offset = self._slot_offset(current_record_count)
                current_page[offset:offset + record_size] = record_bytes
                
                rid = (current_page_id, current_record_count)
                results.append((rid, data_tuple))
                
                current_record_count += 1
                record_count += 1
                
                if record_count % 10_000 == 0:
                    print(f"    {record_count} registros cargados...")
        
        if current_record_count > 0:
            self._write_page_header(current_page, current_record_count)
            self.pm.write_page(current_page_id, bytes(current_page))
            self.last_page_id = current_page_id
        else:
            self.last_page_id = current_page_id - 1
        
        self.total_records = len(results)
        self._persist_metadata()
        
        return results

    def load_from_csv(self, csv_path: str) -> List[Tuple[int, int]]:
        results = self.load_from_csv_optimized(csv_path)
        return [rid for rid, _ in results]

    def _cast_value(self, raw: str, fmt: str):
        fmt_clean = fmt.lstrip('<>=!')
        if fmt_clean[-1] in ('i', 'l', 'q', 'h', 'b', 'I', 'L', 'Q', 'H', 'B'):
            return int(raw)
        elif fmt_clean[-1] in ('f', 'd'):
            return float(raw)
        elif fmt_clean[-1] == 's':
            size = int(fmt_clean[:-1]) if fmt_clean[:-1] else 1
            return raw.encode('utf-8')[:size].ljust(size, b'\x00')
        return raw
    
    def _slot_offset(self, slot_id: int) -> int:
        return self._PAGE_HEADER_SIZE + (slot_id * self.config.get_data_size())
    
    def _read_page_header(self, page: bytes) -> int:
        return struct.unpack(self._PAGE_HEADER_FORMAT, page[:self._PAGE_HEADER_SIZE])[0]
    
    def _write_page_header(self, page: bytearray, record_count: int) -> None:
        header = struct.pack(self._PAGE_HEADER_FORMAT, record_count)
        page[:self._PAGE_HEADER_SIZE] = header
    
    def _read_record_from_slot(self, page: bytes, slot_id: int) -> bytes:
        offset = self._slot_offset(slot_id)
        size = self.config.get_data_size()
        return page[offset:offset + size]
    
    def _write_record_to_slot(self, page: bytearray, slot_id: int, record_bytes: bytes) -> None:
        offset = self._slot_offset(slot_id)
        page[offset:offset + len(record_bytes)] = record_bytes

    def _read_pk_from_slot(self, page: bytes, slot_id: int) -> Any:        
        fmt_body = self.config.data_format.lstrip('<>=!')
        endian   = self.config.data_format[0] if self.config.data_format[0] in '<>=!' else '<'
        tokens   = re.findall(r'\d*[a-zA-Z]', fmt_body)

        pk_byte_offset = sum(
            struct.calcsize(endian + tok)
            for tok in tokens[:self.config.pk_index]
        )
        pk_fmt = endian + tokens[self.config.pk_index]
        pk_size = struct.calcsize(pk_fmt)

        slot_start = self._slot_offset(slot_id)
        raw = page[slot_start + pk_byte_offset : slot_start + pk_byte_offset + pk_size]
        value = struct.unpack(pk_fmt, raw)[0]

        if isinstance(value, bytes):
            return value.decode('utf-8', errors='ignore').rstrip('\x00')
        return value
    
    def _get_deleted_rids(self) -> set:
        # Recorre la lista libre y retorna el conjunto de RIDs eliminados
        deleted_rids: set = set()
        curr_rid = self.first_free_rid
        visited: set = set()

        while curr_rid != (-1, -1):
            if curr_rid in visited:
                # Ciclo detectado: free-list corrupta, detenemos
                break
            visited.add(curr_rid)
            deleted_rids.add(curr_rid)

            page_id, slot_id = curr_rid
            try:
                page = self.pm.read_page(page_id)
                slot_offset = self._slot_offset(slot_id)
                if len(page) >= slot_offset + 8:
                    next_page, next_slot = struct.unpack('<ii', page[slot_offset:slot_offset + 8])
                    curr_rid = (next_page, next_slot)
                else:
                    break
            except Exception:
                break

        return deleted_rids


