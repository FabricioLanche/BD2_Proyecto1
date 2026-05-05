import struct
import time
import hashlib
import pickle
import os
from typing import Optional, Tuple, List

class ExtendibleHashing:
    def __init__(self, page_manager, table_config):
        
        #índice de Hashing Extendible
        #recibe instancias de PageManager y TableConfig para integración total con el motor de base de datos
       
        self.pm = page_manager
        self.config = table_config
        
        #archivo metadatos persistencia directorio y profundidad
        self.filename_meta = f"{self.pm.db_filename}.hash_meta"
        
        #cnfiguración de formatos usando TableConfig
        self.pk_fmt = self.config.get_pk_format()
        self.rid_fmt = 'ii' #valor siempre es un RID: (page_id, slot_id)
        self.record_fmt = f">{self.pk_fmt}{self.rid_fmt}"
        self.record_size = struct.calcsize(self.record_fmt)
        
        #header de página: local_depth (int) y num_records (int)
        self.header_fmt = ">ii"
        self.header_size = struct.calcsize(self.header_fmt)
        
        #capacidad de registros por página 4KB
        self.max_records = (self.pm.PAGE_SIZE - self.header_size) // self.record_size
        
        #carga inicial
        if os.path.exists(self.filename_meta):
            self._load_metadata()
        else:
            self.global_depth = 0
            #reserva nueva página por PageManager
            first_bucket_id = self.pm.allocate_new_page()
            self.directory = [first_bucket_id]
            self._write_bucket(first_bucket_id, 0, [])
            self._save_metadata()

        self.last_execution_time_ms = 0.0


    #compatibilidad para table_stats

    @property
    def n_main(self):
        #retorna total de buckets únicos
        return len(set(self.directory))
        
    @property
    def k_aux(self): return 0 #hash no usa k_aux
    
    @property
    def k_limit(self): return 0 #hash no usa k_limit
    
    @property
    def last_main_page(self):
        #página más alta usada
        return max(self.directory) if self.directory else 0


    #persistencia

    def flush_metadata(self) -> None:
        self._save_metadata()

    def _save_metadata(self):
        with open(self.filename_meta, 'wb') as f:
            pickle.dump({'gd': self.global_depth, 'dir': self.directory}, f)

    def _load_metadata(self):
        with open(self.filename_meta, 'rb') as f:
            data = pickle.load(f)
            self.global_depth = data['gd']
            self.directory = data['dir']


    #operaciones en disco (pagemanager)

    def _read_bucket(self, page_id: int):
        data = self.pm.read_page(page_id)
        
        local_depth, num_records = struct.unpack_from(self.header_fmt, data, 0)
        records = []
        offset = self.header_size
        
        for _ in range(num_records):
            raw = struct.unpack_from(self.record_fmt, data, offset)
            pk = raw[0]
            if isinstance(pk, bytes): 
                pk = pk.rstrip(b'\x00').decode('utf-8', errors='ignore')
            rid = (raw[1], raw[2])
            records.append((pk, rid))
            offset += self.record_size
        return local_depth, records

    def _write_bucket(self, page_id: int, local_depth: int, records: list):
        buffer = bytearray(self.pm.PAGE_SIZE)
        struct.pack_into(self.header_fmt, buffer, 0, local_depth, len(records))
        
        offset = self.header_size
        for pk, rid in records:
            pk_to_pack = pk.encode('utf-8') if isinstance(pk, str) else pk
            struct.pack_into(self.record_fmt, buffer, offset, pk_to_pack, rid[0], rid[1])
            offset += self.record_size
            
        self.pm.write_page(page_id, buffer)

    def _get_hash_bits(self, key, depth):
        h = int(hashlib.md5(str(key).encode()).hexdigest(), 16)
        return h & ((1 << depth) - 1)




    def search_rid(self, pk) -> Optional[Tuple[int, int]]:
        #busca una PK y retorna el RID (page, slot) asociado, None si no existe
        start = time.perf_counter()
        
        idx = self._get_hash_bits(pk, self.global_depth)
        page_id = self.directory[idx]
        local_depth, records = self._read_bucket(page_id)
        
        rid = next((r for k, r in records if k == pk), None)
        
        self.last_execution_time_ms = (time.perf_counter() - start) * 1000
        return rid

    def add(self, pk, rid: Tuple[int, int]):
        #inserta una PK asociada a un RID
        start = time.perf_counter()
        
        idx = self._get_hash_bits(pk, self.global_depth)
        page_id = self.directory[idx]
        local_depth, records = self._read_bucket(page_id)
        
        #reemplazar si ya existe la llave (unique key)
        records = [(k, r) for k, r in records if k != pk]
        records.append((pk, rid))
        
        if len(records) > self.max_records:
            if local_depth == self.global_depth:
                self._double_directory()
            self._split_bucket(idx, page_id, local_depth, records)
        else:
            self._write_bucket(page_id, local_depth, records)
            
        self.last_execution_time_ms = (time.perf_counter() - start) * 1000

    def remove(self, pk) -> Optional[Tuple[int, int]]:
        #elimina una entrada del índice y retorna el RID para que el HeapFile lo elimine.
        start = time.perf_counter()
        idx = self._get_hash_bits(pk, self.global_depth)
        page_id = self.directory[idx]
        local_depth, records = self._read_bucket(page_id)
        
        #buscar RID antes de filtrarlo
        rid_to_delete = None
        new_records = []
        
        for k, r in records:
            if k == pk:
                rid_to_delete = r  #guarda (page_id, slot_id)
            else:
                new_records.append((k, r))
                
        #si se encuentra, guarda la página actualizada y retorna la coordenada
        if rid_to_delete is not None:
            self._write_bucket(page_id, local_depth, new_records)
            self.last_execution_time_ms = (time.perf_counter() - start) * 1000
            return rid_to_delete
            
        return None  #none si no existe

    #reestructuracion
    def _double_directory(self):
        self.directory.extend(self.directory[:])
        self.global_depth += 1
        self._save_metadata()

    def _split_bucket(self, index, old_page_id, local_depth, all_records):
        new_depth = local_depth + 1
        new_page_id = self.pm.allocate_new_page()
        
        b0, b1 = [], []
        pattern_orig = self._get_hash_bits(index, new_depth)
        
        #redistribuir basándose en el bit extra
        for k, r in all_records:
            if self._get_hash_bits(k, new_depth) == pattern_orig:
                b0.append((k, r))
            else:
                b1.append((k, r))
        
        self._write_bucket(old_page_id, new_depth, b0)
        self._write_bucket(new_page_id, new_depth, b1)
        
        #actualizar punteros del directorio
        mask = (1 << new_depth) - 1
        pattern_new = pattern_orig ^ (1 << local_depth)
        
        for i in range(len(self.directory)):
            if (i & mask) == pattern_orig:
                self.directory[i] = old_page_id
            elif (i & mask) == pattern_new:
                self.directory[i] = new_page_id
        
        self._save_metadata()