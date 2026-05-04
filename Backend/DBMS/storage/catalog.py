import json
import math
import os
from DBMS.organization.page_manager import PageManager

class SystemCatalog:
    def __init__(self, filename="system_catalog.dat"):
        self.filename = filename
        self.pm = PageManager(filename)
        self.metadata = {} 
        if not os.path.exists(self.filename):
            # Si no existe, lo creamos con un diccionario vacío
            with open(self.filename, 'w') as f:
                json.dump({}, f)
        self._load_catalog()

    def _load_catalog(self):
        data = self.pm.read_page(0)

        if not data:
            self.metadata = {}
            return
        
        clean_json = data.replace(b'\x00', b'').decode('utf-8')
        if clean_json:
            try:
                self.metadata = json.loads(clean_json)
            except json.JSONDecodeError:
                self.metadata = {}

    def _save_catalog(self):
        json_string = json.dumps(self.metadata)
        json_bytes = json_string.encode('utf-8')
        
        page_size = self.pm.PAGE_SIZE
        num_pages = math.ceil(len(json_bytes) / page_size) or 1
        
        for i in range(num_pages):
            chunk = json_bytes[i * page_size : (i + 1) * page_size]
            self.pm.write_page(i, chunk)

    def create_table(self, table_name, columns_ast):
        # Soporte para solo 1 tabla, es decir se sobrescribe la tabla actual del catalogo con la nueva
        self.metadata = {table_name: columns_ast}
        self._save_catalog()

    def get_table_schema(self, table_name):
        if table_name not in self.metadata:
            raise Exception(f"La tabla '{table_name}' no existe en el catálogo.")
        return self.metadata[table_name]