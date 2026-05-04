
class SQLParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self): 
        return self.tokens[self.pos]

    def match(self, expected_type):
        if self.current().type == expected_type:
            token = self.current()
            self.pos += 1
            return token
        raise SyntaxError(f"Error Sintáctico: Se esperaba {expected_type}, se encontró {self.current().type} ('{self.current().value}')")

    def parse(self): # equivalente a program en la gramatica
        statements = []
        while self.current().type != 'EOF':
            statements.append(self.parse_statement())
            if self.current().type == 'OP' and self.current().value == ';':
                self.match('OP') 
        return statements

    def parse_statement(self):
        t = self.current().type
        if t == 'CREATE': return self.create_stmt()
        if t == 'SELECT': return self.select_stmt()
        if t == 'INSERT': return self.insert_stmt()
        if t == 'DELETE': return self.delete_stmt()
        raise SyntaxError(f"Sentencia SQL no reconocida iniciando con: {t}")

    def create_stmt(self):
        self.match('CREATE')
        table_name = self.match('ID').value
        self.match('OP') # (
        
        columns = []
        while True:
            col_name = self.match('ID').value
            
            # tipo de Dato de columna
            if self.current().type == 'POINT_TYPE':
                col_type = self.match('POINT_TYPE').value.upper()
            else:
                col_type = self.match('TYPE').value.upper()
                if col_type == 'VARCHAR':
                    self.match('OP') # (
                    size = self.match('NUM').value
                    self.match('OP') # )
                    col_type = f"VARCHAR({size})"

            is_primary = False
            if self.current().type == 'PRIMARY':
                self.match('PRIMARY')
                self.match('KEY')
                is_primary = True

            index_tech = None
            if self.current().type == 'INDEX':
                self.match('INDEX')
                index_tech = self.match('TECH').value.upper()
                
            columns.append({
                "nombre": col_name, 
                "tipo": col_type, 
                "primary_key": is_primary,
                "index_tech": index_tech
            })
            
            if self.current().value == ')': break
            self.match('OP') # ,
            
        self.match('OP') # )
        
        # archivo para la carga de datos (opcional )
        filepath = None
        if self.current().type == 'FROM_FILE':
            self.match('FROM_FILE')
            filepath = self.match('STRING').value.replace('"', '')
            
        return {"action": "CREATE", "table": table_name, "columns": columns, "file": filepath}

    def select_stmt(self):
        self.match('SELECT')

        if self.current().value == '*':
            self.match('OP') 
            selector = '*'
        else:
            selector = self.parse_id_list()

        self.match('FROM')
        table = self.match('ID').value

        self.match('WHERE')
        col = self.match('ID').value
        
        curr = self.current()
        if curr.value == '=':
            self.match('OP')
            val = self.match('NUM').value if self.current().type == 'NUM' else self.match('STRING').value.replace('"', '')
            return {"action": "SELECT", "type": "SEARCH", "table": table, "col": col, "val": val}
        
        elif curr.type == 'BETWEEN':
            self.match('BETWEEN')
            v1 = float(self.match('NUM').value)
            self.match('AND')
            v2 = float(self.match('NUM').value)
            return {"action": "SELECT", "type": "RANGE", "table": table, "col": col, "range": [v1, v2]}
            
        elif curr.type == 'IN':
            self.match('IN')
            self.match('OP') # (
            self.match('POINT_TYPE')
            self.match('OP') # (
            x = float(self.match('NUM').value)
            self.match('OP') # ,
            y = float(self.match('NUM').value)
            self.match('OP') # )
            self.match('OP') # ,
            
            if self.current().type == 'RADIUS':
                self.match('RADIUS')
                r = float(self.match('NUM').value)
                self.match('OP') # )
                return {"action": "SELECT", "type": "RTREE_RADIUS", "table": table, "point": [x, y], "radius": r}
                
            elif self.current().type == 'K':
                self.match('K')
                k = int(self.match('NUM').value)
                self.match('OP') # )
                return {"action": "SELECT", "type": "RTREE_KNN", "table": table, "point": [x, y], "k": k}

    def parse_id_list(self):
        ids = []
        ids.append(self.match('ID').value)
        
        while self.current().type == 'OP' and self.current().value == ',':
            self.match('OP') 
            ids.append(self.match('ID').value)
        
        return ids

    def insert_stmt(self):
        self.match('INSERT')
        table = self.match('ID').value
        self.match('VALUES')
        self.match('OP') # (
        
        values = []
        while True:
            curr = self.current()
            if curr.type == 'NUM':
                val = float(curr.value) if '.' in curr.value else int(curr.value)
                values.append(val)
                self.match('NUM')
            elif curr.type == 'STRING':
                values.append(curr.value.replace('"', ''))
                self.match('STRING')
            elif curr.type == 'POINT_TYPE':
                self.match('POINT_TYPE')
                self.match('OP') # (
                x = float(self.match('NUM').value)
                self.match('OP') # ,
                y = float(self.match('NUM').value)
                self.match('OP') # )
                values.append((x, y)) # Lo guardamos como una tupla de Python
            else:
                raise SyntaxError("Valor inválido en VALUES")
            
            if self.current().value == ')': break
            self.match('OP') # ,
            
        self.match('OP') # )
        return {"action": "INSERT", "table": table, "values": values}

    def delete_stmt(self):
        self.match('DELETE')
        table = self.match('ID').value
        self.match('WHERE')
        col = self.match('ID').value
        self.match('OP') # =
        if self.current().type == 'NUM':
            val = self.match('NUM').value
        else:
            val = self.match('STRING').value.replace('"', '')
        return {"action": "DELETE", "table": table, "col": col, "val": val}