   #Capa 1: Acceso a Disco
import os
from Backend.DBMS.config import get_index_page_size

class PageManager:
    def __init__(self, db_filename, io_counter=None, page_size=None):
        self.db_filename = db_filename
        # Si no se especifica, tomar tamaño desde la configuración central
        if page_size is None:
            page_size = get_index_page_size()
        self.PAGE_SIZE = page_size  # Tamaño de página configurable
        self.read_count = 0
        self.write_count = 0
        #Contador global de I/O compartido
        self.io_counter  = io_counter

        self.last_page_id_loaded = -1
        self.last_page_data = None

        if not os.path.exists(db_filename):
          with open(db_filename, 'wb') as f:
              pass

    def read_page(self, page_id):
        if page_id == self.last_page_id_loaded:
            return self.last_page_data
        self.read_count += 1

        if self.io_counter:
            self.io_counter.add_read()

        offset = page_id * self.PAGE_SIZE
        with open(self.db_filename, 'rb') as f:
            f.seek(offset)
            data_leida = f.read(self.PAGE_SIZE)

        #Si el contenido de la pagina no llega a ser 4KB, rellenamos con 0s
        if len(data_leida) < self.PAGE_SIZE:
           data_leida = data_leida.ljust(self.PAGE_SIZE, b'\x00')
        self.last_page_id_loaded = page_id
        self.last_page_data = data_leida
        return data_leida

    def write_page(self, page_id, data):
        self.write_count += 1
        if self.io_counter:
            self.io_counter.add_write()
        offset = page_id * self.PAGE_SIZE
        with open(self.db_filename, 'r+b') as f:
            f.seek(offset)
            f.write(data.ljust(self.PAGE_SIZE, b'\x00'))
            
        # Si la pagina es la misma en cache, reiniciamos el cache para mantener la consistencia (version)
        if page_id == self.last_page_id_loaded:
          self.last_page_id_loaded = -1
          self.last_page_data = None

    def invalidate_cache(self):
        self.last_page_id_loaded = -1
        self.last_page_data = None

    def reset_counters(self):
        self.read_count = 0
        self.write_count = 0

    def get_stats(self):
        return {
            "reads": self.read_count,
            "writes": self.write_count,
            "total": self.read_count + self.write_count
        }
    def allocate_new_page(self) -> int:
        # Asigna una nueva página
        file_size = os.path.getsize(self.db_filename)
        
        if file_size % self.PAGE_SIZE != 0:
            raise ValueError(
                f"Archivo corrupto: tamaño {file_size} bytes "
                f"no es múltiplo de PAGE_SIZE ({self.PAGE_SIZE})"
            )
        
        new_page_id = file_size // self.PAGE_SIZE
        
        try:
            with open(self.db_filename, 'r+b') as f:
                f.seek(0, 2)
                f.write(b'\x00' * self.PAGE_SIZE)
                f.flush()  # Forzar escritura a disco
        except IOError as e:
            raise IOError(f"Error al escribir nueva página: {e}")
        
        self.write_count += 1
        
        return new_page_id
    
class IOCounter:
    # Contador global de I/O compartido
    
    def __init__(self):
        self.reads  = 0
        self.writes = 0
    
    def add_read(self):
        self.reads += 1
    
    def add_write(self):
        self.writes += 1
    
    def reset(self):
        self.reads  = 0
        self.writes = 0
    
    def snapshot(self) -> dict:
        return {
            "reads":  self.reads,
            "writes": self.writes,
            "total":  self.reads + self.writes
        }