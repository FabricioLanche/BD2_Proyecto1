import struct
import re 
from typing import Tuple, Any, Optional

class TableConfig:
    # Representar qué forma tienen los datos que el usuario insertó.
    def __init__(self, data_format: str, column_names):
        self.data_format = data_format
        self.data_size = struct.calcsize(self.data_format)
        # Mapeo: dónde está cada atributo en la tupla
        self.column_map = {name: idx for idx, name in enumerate(column_names)}
        
    def get_data_size(self) -> int:
        return self.data_size
    
    def get_column_format(self, column_name: str) -> str:
        fmt = self.data_format.lstrip('<>=!')
        tokens = re.findall(r'\d*[a-zA-Z]', fmt)
        idx = self.column_map[column_name]
        return tokens[idx]

    def get_pk_format(self) -> str:
        # La PK es índice 0 — busca el nombre con idx=0
        pk_name = next(name for name, idx in self.column_map.items() if idx == 0)
        return self.get_column_format(pk_name)

class Record:
    #Envoltorio de datos en RAM

    def __init__(self, data_tuple: Tuple[Any, ...], table_config: Optional[TableConfig] = None):
        self.data_tuple = data_tuple
        self.config = table_config
        # Limpiar strings: remover \x00 padding de bytes
        self.cleaned_values = self._clean_values(data_tuple)
    
    def _clean_values(self, data_tuple: Tuple) -> list:
        cleaned = []
        for val in data_tuple:
            if isinstance(val, bytes):
                # Decodificar y quitar padding nulo
                cleaned.append(val.decode('utf-8', errors='ignore').rstrip('\x00'))
            else:
                cleaned.append(val)
        return cleaned
    
    def get_pk(self):
        # Asumimos que la PK esta en la posicion 0
        return self.data_tuple[0]
        
    def get_attribute(self, column_name):
        idx = self.config.column_map[column_name]
        valor = self.data_tuple[idx]
        
        # Opcional: Limpiar strings de bytes nulos (\x00) que deja struct
        if isinstance(valor, bytes):
            return valor.decode('utf-8').rstrip('\x00')
        return valor
    
    def to_bytes(self, table_config: TableConfig) -> bytes:
        return struct.pack(table_config.data_format, *self.data_tuple)
    
    def __repr__(self) -> str:
        return f"Record(PK={self.get_pk()}, Values={self.cleaned_values})"

class Page:
    def __init__(self, page_id, data):
        self.page_id = page_id
        self.next_page_ptr = -1
        self.data = data

        self.records = []
class Header:
    def __init__(self, t_registros_fisicos, cantidad_auxiliar, primer_registro_logico):
        self.t_registros_fisicos = t_registros_fisicos
        self.cantidad_auxiliar = cantidad_auxiliar
        self.primer_registro_logico = primer_registro_logico
