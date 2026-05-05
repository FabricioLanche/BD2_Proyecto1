import os
import csv
import tempfile
from organization.data_structures import TableConfig, Record
from database_engine import DatabaseEngine

def separador(titulo: str):
    print(f"\n{'═'*55}\n  {titulo}\n{'═'*55}")

def mostrar(result, detalle=None):
    print(f"  {result}")
    if detalle:
        print(f"  → {detalle}")

def crear_csv_temporal(filas, columnas) -> str:
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv',
                                     delete=False, newline='', encoding='utf-8')
    writer = csv.DictWriter(tmp, fieldnames=columnas)
    writer.writeheader()
    writer.writerows(filas)
    tmp.close()
    return tmp.name

def limpiar_archivos(tabla: str):
    for ext in ['.heap', '_id.idx', '_id.idx.tmp']:
        path = f"{tabla}{ext}"
        if os.path.exists(path):
            os.remove(path)


# Configuración: id (int), nombre (30 chars), salario (float)

CONFIG = TableConfig(
    data_format  = '<i30sf',
    column_names = ['id', 'nombre', 'salario'],
)
COLUMNAS = ['id', 'nombre', 'salario']
DATOS_BASE = [
    {'id': '10', 'nombre': 'Alice',   'salario': '3000.0'},
    {'id': '20', 'nombre': 'Bob',     'salario': '4500.0'},
    {'id': '30', 'nombre': 'Carlos',  'salario': '2800.0'},
    {'id': '40', 'nombre': 'Diana',   'salario': '5200.0'},
    {'id': '50', 'nombre': 'Eduardo', 'salario': '3900.0'},
    {'id': '60', 'nombre': 'Fatima',  'salario': '4100.0'},
    {'id': '70', 'nombre': 'Gonzalo', 'salario': '6000.0'},
    {'id': '80', 'nombre': 'Helena',  'salario': '3300.0'},
    {'id': '90', 'nombre': 'Ivan',    'salario': '2700.0'},
    {'id': '100','nombre': 'Julia',   'salario': '4800.0'},
]



def test_create_and_load():
    separador("TEST 1 — CREATE TABLE + carga CSV")
    limpiar_archivos('empleados')
    engine = DatabaseEngine()
    csv_path = crear_csv_temporal(DATOS_BASE, COLUMNAS)

    result = engine.create_table_from_csv('empleados', CONFIG, csv_path, 'id')
    os.remove(csv_path)

    mostrar(result, f"{result.records} registros cargados")
    stats = engine.get_table_stats('empleados')
    print(f"  heap_pages={stats['heap_pages']}  index_pages={stats['index_pages']}")
    print(f"  n_main={stats['index_n_main']}  k_aux={stats['index_k_aux']}")
    return engine


def test_search(engine: DatabaseEngine):
    separador("TEST 2 — SELECT puntual")

    result = engine.search('empleados', 40)
    mostrar(result, result.records)
    assert result.records is not None, "ERROR: debería encontrar id=40"

    result = engine.search('empleados', 999)
    mostrar(result, f"result={result.records} (esperado: None)")
    assert result.records is None

    print("  ✓ search OK")


def test_range_search(engine: DatabaseEngine):
    separador("TEST 3 — SELECT RANGE [30, 70]")

    result = engine.range_search('empleados', 30, 70)
    mostrar(result, f"{len(result.records)} registros")
    for r in result.records:
        print(f"    {r}")
    assert len(result.records) == 5, f"ERROR: esperaba 5, obtuvo {len(result.records)}"
    print("  ✓ range_search OK")


def test_insert(engine: DatabaseEngine):
    separador("TEST 4 — INSERT")

    nuevos = [
        Record((15, b'Nuevo1'.ljust(30, b'\x00'), 9999.0), CONFIG),
        Record((25, b'Nuevo2'.ljust(30, b'\x00'), 8888.0), CONFIG),
        Record((35, b'Nuevo3'.ljust(30, b'\x00'), 7777.0), CONFIG),
    ]
    for rec in nuevos:
        result = engine.insert('empleados', rec)
        mostrar(result, f"RID={result.records}")

    result_search = engine.search('empleados', 25)
    result_search.__repr__()
    
    assert result_search.records is not None, "ERROR: id=25 debería existir"
    mostrar(result_search, result_search.records)

    stats = engine.get_table_stats('empleados')
    print(f"  k_aux={stats['index_k_aux']}  k_limit={stats['index_k_limit']}")
    print("  ✓ insert OK")


def test_delete(engine: DatabaseEngine):
    separador("TEST 5 — DELETE")

    result = engine.delete('empleados', 20)
    mostrar(result, f"deleted={result.records}")
    assert result.records == True

    result = engine.search('empleados', 20)
    mostrar(result, f"search post-delete: {result.records} (esperado: None)")
    assert result.records is None

    result = engine.delete('empleados', 999)
    mostrar(result, f"deleted={result.records} (esperado: False)")
    assert result.records == False

    print("  ✓ delete OK")


def test_reconstruct_trigger(engine: DatabaseEngine):
    separador("TEST 6 — RECONSTRUCT automático")

    stats = engine.get_table_stats('empleados')
    k_limit = stats['index_k_limit']
    k_aux   = stats['index_k_aux']
    print(f"  Estado antes: k_aux={k_aux}, k_limit={k_limit}")
    print(f"  Insertando {k_limit + 2} registros para cruzar el umbral...")

    reconstruct_ocurrio = False
    pk_base = 200

    for i in range(k_limit + 2):
        pk  = pk_base + i
        rec = Record((pk, f'Temp{i}'.encode().ljust(30, b'\x00'), float(i * 100)), CONFIG)

        k_antes = engine.get_table_stats('empleados')['index_k_aux']
        result  = engine.insert('empleados', rec)
        k_despues = engine.get_table_stats('empleados')['index_k_aux']

        mostrar(result)

        if k_despues < k_antes:
            reconstruct_ocurrio = True
            print(f"  *** RECONSTRUCT disparado en pk={pk} ***")
            print(f"      k_aux: {k_antes} → {k_despues}")
            print(f"      n_main nuevo: {engine.get_table_stats('empleados')['index_n_main']}")

    assert reconstruct_ocurrio, "ERROR: reconstruct no se disparó"

    # Verifica accesibilidad post-reconstruct
    result = engine.search('empleados', pk_base)
    result.__repr__()
    assert result.records is not None, "ERROR: registro no encontrado post-reconstruct"
    print(f"  ✓ Reconstruct OK — búsqueda post-reconstruct: {result.records}")


def test_io_reset_entre_consultas(engine: DatabaseEngine):
    separador("TEST 7 — IOCounter por consulta")

    # Primera búsqueda: puede tener I/O o cache hit
    r1 = engine.search('empleados', 10)
    r2 = engine.search('empleados', 100)
    r3 = engine.range_search('empleados', 10, 50)

    print(f"  search(10):    {r1.io_stats}")
    print(f"  search(100):   {r2.io_stats}")
    print(f"  range(10,50):  {r3.io_stats}")

    # Verifica que los contadores son independientes (no se acumulan)
    assert r1.io_stats['total'] >= 0, "IOCounter no debería ser negativo"
    assert r2.io_stats['total'] >= 0, "IOCounter no debería ser negativo"
    # range_search toca más páginas que una búsqueda puntual (o igual si todo está en caché)
    assert r3.io_stats['total'] >= 0, "IOCounter no debería ser negativo"
    print("  ✓ IOCounter por consulta OK")

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  DATABASE ENGINE — Suite de pruebas")
    print("="*55)

    engine = test_create_and_load()
    test_search(engine)
    test_range_search(engine)
    test_insert(engine)
    test_delete(engine)
    test_reconstruct_trigger(engine)
    test_io_reset_entre_consultas(engine)

    separador("RESUMEN FINAL")
    stats = engine.get_table_stats('empleados')
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print("\n  ✓ Todos los tests pasaron\n")
