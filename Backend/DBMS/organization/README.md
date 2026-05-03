# Sequential File Implementation - Capa de Organización

## 📋 Estructura de Módulos

```
organization/
├── page_manager.py          # Capa 1: Acceso a disco (4KB páginas)
├── data_structures.py       # Capa 2: Estructuras en RAM (Record, Header, TableConfig)
├── sequential_file.py       # Capa 3: Lógica del Sequential File
└── README.md                # Este archivo
```

## 🏗️ Arquitectura de 3 Capas

| Capa | Módulo | Responsabilidad |
|------|--------|-----------------|
| **Capa 1** | `page_manager.py` | Lectura/escritura física de páginas 4KB |
| **Capa 2** | `data_structures.py` | Estructuras en RAM: Record, Header, TableConfig |
| **Capa 3** | `sequential_file.py` | Orquestador: lógica CRUD, búsqueda, reconstrucción |

---

## 🚀 Uso Básico

```python
from organization.page_manager import PageManager
from organization.data_structures import TableConfig, Header
from organization.sequential_file import SequentialFile

# Configurar tabla
config = TableConfig(
    table_name="employees",
    columns_format='i30si20s20s20sf10si',  # ID + nombre + age + país + depto + puesto + salario + fecha + next
    column_names=['employee_id', 'employee_name', 'age', 'country', 'department', 'position', 'salary', 'joining_date', 'next']
)

# Crear PageManager
page_manager = PageManager("database/employees.dat")

# Crear Sequential File (carga CSV si no existe .dat)
seq_file = SequentialFile(
    config=config,
    page_manager=page_manager,
    csv_filename="employee.csv"
)

# Usar
record = seq_file.search(employee_id=12345)
seq_file.insert(record)
seq_file.remove(employee_id=12345)
results = seq_file.rangeSearch(10000, 10050)
```

---

## 📊 Métricas y Accesos a Disco

El `PageManager` rastrea automáticamente:

```python
# Antes de operación
page_manager.reset_counters()

# Operación (search, insert, etc.)
result = seq_file.search(12345)

# Obtener métricas
stats = page_manager.get_stats()
print(f"Lecturas: {stats['reads']}")
print(f"Escrituras: {stats['writes']}")
print(f"Total accesos: {stats['total']}")
```

---

## 🔍 Troubleshooting

### Problema: `ModuleNotFoundError: No module named 'organization'`
**Solución:** Asegurate de estar en la raíz del proyecto y que `.venv` esté activado

### Problema: `FileNotFoundError: employee.csv`
**Solución:** Coloca `employee.csv` en el mismo directorio donde ejecutas el script

### Problema: Permiso denegado al escribir `.dat`
**Solución:** Asegurate de tener permisos de escritura en la carpeta `database/`

---

## 📝 Notas Importantes

- **HEADER_SIZE = 12 bytes** → Específico de Sequential File (3 ints × 4 bytes)
- **PAGE_SIZE = 4096 bytes** → Constante universal
- **next_pos es global** → Posición en bytes desde el inicio del archivo
- **Cache de página** → PageManager cachea la última página leída

---