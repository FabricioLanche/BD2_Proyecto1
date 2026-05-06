import struct
import re 
from typing import Tuple, Any, Optional

class TableConfig:
    # Representar qué forma tienen los datos que el usuario insertó.
    def __init__(self, data_format: str, column_names, pk_col_name: str = "id"):
        self.data_format = data_format
        self.data_size = struct.calcsize(self.data_format)
        self.pk_index = 0
        self.pk_col_name = pk_col_name

        self.pk_index = 0
        self.pk_col_name = pk_col_name

        # Mapeo: dónde está cada atributo en la tupla
        self.column_map = {name: idx for idx, name in enumerate(column_names)}

        if pk_col_name in self.column_map:
            self.pk_index = self.column_map[pk_col_name]

        if pk_col_name in self.column_map:
            self.pk_index = self.column_map[pk_col_name]
        
    def get_data_size(self) -> int:
        return self.data_size
    
    def get_column_format(self, column_name: str) -> str:
        fmt = self.data_format.lstrip('<>=!')
        tokens = re.findall(r'\d*[a-zA-Z]', fmt)
        idx = self.column_map[column_name]
        return tokens[idx]

    def get_pk_format(self) -> str:
        # La PK es índice 0 — busca el nombre con idx=0
        pk_name = next(name for name, idx in self.column_map.items() if idx == self.pk_index)
        pk_name = next(name for name, idx in self.column_map.items() if idx == self.pk_index)
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
        #return self.data_tuple[0]
        return self.data_tuple[self.config.pk_index]
        
    def get_attribute(self, column_name):
        idx = self.config.column_map[column_name]
        valor = self.data_tuple[idx]
        
        if isinstance(valor, bytes):
            return valor.decode('utf-8').rstrip('\x00')
        return valor
    
    def to_bytes(self, table_config: TableConfig) -> bytes:
        return struct.pack(table_config.data_format, *self.data_tuple)
    
    def __repr__(self) -> str:
        return f"Record(PK={self.get_pk()}, Values={self.cleaned_values})"
