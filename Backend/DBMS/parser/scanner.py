import re

class Token:
    def __init__(self, type, value):
        self.type = type
        self.value = value

    def __repr__(self):
        return f"Token({self.type}, {self.value})"

class Scanner:
    # terminales
    # \b indica limite de palabra para no confundir IDs con palabras reservadas
    # \s+ significa uno o más espacios
    patterns = [
        ('CREATE', r'CREATE\s+TABLE\b'),
        ('SELECT', r'SELECT\b'),
        ('INSERT', r'INSERT\s+INTO\b'),
        ('DELETE', r'DELETE\s+FROM\b'),
        ('FROM_FILE', r'FROM\s+FILE\b'),
        ('FROM', r'FROM\b'),
        ('WHERE', r'WHERE\b'),
        ('BETWEEN', r'BETWEEN\b'),
        ('AND', r'AND\b'),
        ('IN', r'IN\b'),
        ('VALUES', r'VALUES\b'),
        ('POINT_TYPE', r'POINT\b'), 
        ('RADIUS', r'RADIUS\b'),
        ('K', r'K\b'),
        ('INDEX', r'INDEX\b'),
        ('TYPE', r'INT|DOUBLE|VARCHAR'),
        ('TECH', r'HASH|BTREE|RTREE|SEQUENTIAL\b'),
        ('PRIMARY', r'PRIMARY\b'),
        ('KEY', r'KEY\b'),
        ('ID', r'[a-zA-Z_][a-zA-Z0-9_]*'),
        ('NUM', r'-?\d+(\.\d+)?'),
        ('STRING', r'"[^"]*"'),
        ('OP', r'[=,();*]'),
        ('SPACE', r'\s+'),
    ]

    def __init__(self, text):
        self.text = text
        self.tokens = []

    def tokenize(self):
        pos = 0
        while pos < len(self.text):
            match = None
            for name, pattern in self.patterns:
                regex = re.compile(pattern, re.IGNORECASE) # Ignorar si es mayusculas/minusculas
                match = regex.match(self.text, pos)
                if match:
                    if name != 'SPACE':
                        self.tokens.append(Token(name, match.group(0)))
                    pos = match.end(0)
                    break
            
            if not match:
                raise SyntaxError(f"Error Léxico: Carácter no reconocido en posición {pos}: '{self.text[pos]}'")
        
        self.tokens.append(Token('EOF', None))
        return self.tokens