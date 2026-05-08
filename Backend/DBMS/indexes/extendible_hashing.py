import struct
import time
import hashlib
import pickle
import os
from typing import Tuple, List
import math

class ExtendibleHashing:
    def __init__(self, page_manager, table_config, column_name):
        
        #índice de Hashing Extendible
        #recibe instancias de PageManager y TableConfig para integración total con el motor de base de datos
       
        self.pm = page_manager
        self.config = table_config
        self.column_name = column_name
        
        #archivo metadatos persistencia directorio y profundidad
        self.filename_meta = f"{self.pm.db_filename}.hash_meta"
        
        #cnfiguración de formatos usando TableConfig
        self.key_fmt = self.config.get_column_format(self.column_name)
        self.rid_fmt = 'ii' #valor siempre es un RID: (page_id, slot_id)
        self.record_fmt = f">{self.key_fmt}{self.rid_fmt}"
        self.record_size = struct.calcsize(self.record_fmt)
        
        #header de página: local_depth (int), num_records (int) y next_page_id (int)(buckets enlazados)
        self.header_fmt = ">iii"
        self.header_size = struct.calcsize(self.header_fmt)
        
        #capacidad de registros por página 4KB
        self.max_records = (self.pm.PAGE_SIZE - self.header_size) // self.record_size
        
        #calculo dinamico de max global depth
        #definir cuántos registros espera soportar como máximo (100k)
        expected_records = getattr(self.config, 'expected_rows', 100000)
        
        #calcular páginas necesarias y logaritmo base 2
        paginas_necesarias = expected_records / max(1, self.max_records)
        if paginas_necesarias <= 1:
            self.MAX_GLOBAL_DEPTH = 1
        else:
            #techo
            self.MAX_GLOBAL_DEPTH = math.ceil(math.log2(paginas_necesarias))
            

        #carga inicial
        if os.path.exists(self.filename_meta):
            self._load_metadata()
        else:
            self.global_depth = 0
            #reserva nueva página por PageManager
            first_bucket_id = self.pm.allocate_new_page()
            self.directory = [first_bucket_id]
            self._write_bucket([first_bucket_id], 0, [])
            self._save_metadata()

        self.last_execution_time_ms = 0.0


    #compatibilidad para table_stats

    @property
    def n_main(self):
        #retorna total de buckets únicos
        return len(set(self.directory))
        
    @property
    def k_aux(self): 
        return 0 #hash no usa k_aux
    
    @property
    def k_limit(self): 
        return 0 #hash no usa k_limit
    
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

    def _read_bucket(self, start_page_id: int):
        #lee una pagina y sigue a next_page_id si hay chaining
        records = []
        chain_pages = []
        current_page = start_page_id
        local_depth = 0

        while current_page != -1:
            chain_pages.append(current_page)
            data = self.pm.read_page(current_page)
            
            #unpack el header de 3 elementos
            ld, num_records, next_page = struct.unpack_from(self.header_fmt, data, 0)
            
            if current_page == start_page_id:
                local_depth = ld
            
            offset = self.header_size
            for _ in range(num_records):
                raw = struct.unpack_from(self.record_fmt, data, offset)
                pk = raw[0]
                if isinstance(pk, bytes): 
                    pk = pk.rstrip(b'\x00').decode('utf-8', errors='ignore')
                rid = (raw[1], raw[2])
                records.append((pk, rid))
                offset += self.record_size
            
            #siguiente bucket en la cadena
            current_page = next_page 
            
        return local_depth, records, chain_pages

    def _write_bucket(self, chain_pages: list, local_depth: int, all_records: list):
        #escribe una lista de registros, overflow pages si es necesario

        #cortar lista en chunks del tamaño máximo de una página
        chunks = [all_records[i:i + self.max_records] for i in range(0, max(1, len(all_records)), self.max_records)]
        
        #si mas chunks que buckets fisicos disponibles, pedimos páginas nuevas a pm
        while len(chain_pages) < len(chunks):
            chain_pages.append(self.pm.allocate_new_page())
            
        #escribir cada chunk en bucket correspondiente, actualizando header con local_depth, num_records y next_page_id
        for i, chunk in enumerate(chunks):
            page_id = chain_pages[i]
            #si hay un chunk siguiente, apuntamos a ese bucket. Si no -1
            next_page_id = chain_pages[i+1] if i + 1 < len(chunks) else -1
            
            buffer = bytearray(self.pm.PAGE_SIZE)
            struct.pack_into(self.header_fmt, buffer, 0, local_depth, len(chunk), next_page_id)
            
            offset = self.header_size
            for pk, rid in chunk:
                pk_to_pack = pk.encode('utf-8') if isinstance(pk, str) else pk
                struct.pack_into(self.record_fmt, buffer, offset, pk_to_pack, rid[0], rid[1])
                offset += self.record_size
                
            self.pm.write_page(page_id, buffer)

    def _get_hash_bits(self, key, depth):
        h = int(hashlib.md5(str(key).encode()).hexdigest(), 16)
        return h & ((1 << depth) - 1)




    def search_rid(self, key) -> List[Tuple[int, int]]:
        #busca segun columna y retorna lista de RIDs (page, slot) asociados (duplicados), None si no existe
        start = time.perf_counter()
        
        idx = self._get_hash_bits(key, self.global_depth)
        page_id = self.directory[idx]
        _, records, _ = self._read_bucket(page_id)
        
        rids = [r for k, r in records if k == key]
        
        self.last_execution_time_ms = (time.perf_counter() - start) * 1000
        return rids

    def add(self, key, rid: Tuple[int, int]):
        #inserta una key asociada a un RID
        start = time.perf_counter()
        
        idx = self._get_hash_bits(key, self.global_depth)
        page_id = self.directory[idx]
        local_depth, records, chain_pages = self._read_bucket(page_id)
        
        #añade neuvo registro (duplicados)
        records.append((key, rid))
        
        if len(records) > self.max_records:
            #si llegamos al límite máximo, NO hacemos split, se aplica chianing
            if local_depth >= self.MAX_GLOBAL_DEPTH:
                self._write_bucket(chain_pages, local_depth, records)
            else:
                if local_depth == self.global_depth:
                    self._double_directory()
                self._split_bucket(idx, page_id, local_depth, records, chain_pages)
        else:
            self._write_bucket(chain_pages, local_depth, records)
            
        self.last_execution_time_ms = (time.perf_counter() - start) * 1000

    def remove(self, key) -> List[Tuple[int, int]]:
        start = time.perf_counter()
        #elimina una entrada del índice y retorna el RID
        idx = self._get_hash_bits(key, self.global_depth)
        page_id = self.directory[idx]
        local_depth, records, chain_pages = self._read_bucket(page_id)
        
        #buscar RID antes de filtrarlo
        rids_to_delete = []
        new_records = []
        
        for k, r in records:
            if k == key:
                rids_to_delete.append(r)  #guarda (page_id, slot_id), si duplicado guarda en lista
            else:
                new_records.append((k, r))
                
        #si se borra al menos un registro de la lista, actualiza disco
        if rids_to_delete:
            self._write_bucket(chain_pages, local_depth, new_records)
        
        self.last_execution_time_ms = (time.perf_counter() - start) * 1000
        return rids_to_delete #retorna lista de rids, vacia si no encontro nada
            

    #reestructuracion
    def _double_directory(self):
        self.directory.extend(self.directory[:])
        self.global_depth += 1
        self._save_metadata()

    def _split_bucket(self, index, old_page_id, local_depth, all_records, old_chain_pages):
        new_depth = local_depth + 1        
        b0, b1 = [], []
        
        #recuperar patrón binario real que compartían las llaves del bucket
        pattern_orig = index & ((1 << local_depth) - 1)
        
        #calcular nuevo patrón (igual al original, pero con un 1 en el nuevo bit extra)
        pattern_new = pattern_orig | (1 << local_depth)
        
        #redistribuir usando hash de cada llave
        for k, r in all_records:
            if self._get_hash_bits(k, new_depth) == pattern_orig:
                b0.append((k, r))
            else:
                b1.append((k, r))
        
        #bucket 0 reutiliza las páginas antiguas
        self._write_bucket(old_chain_pages, new_depth, b0)

        #bucket 1 se crea con una página nueva
        new_page_id = self.pm.allocate_new_page()
        self._write_bucket([new_page_id], new_depth, b1)

        #actualizar los punteros del directorio
        mask = (1 << new_depth) - 1
        
        for i in range(len(self.directory)):
            if (i & mask) == pattern_orig:
                self.directory[i] = old_page_id
            elif (i & mask) == pattern_new:
                self.directory[i] = new_page_id
        
        self._save_metadata()