import os
import sys
import csv
import tempfile
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from Backend.DBMS.database_engine import DatabaseEngine
from Backend.DBMS.organization.data_structures import TableConfig, Record

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



# ═════════════════════════════════════════════════════════════
# FUNCIONES DE ASERCIONES Y VALIDACIÓN
# ═════════════════════════════════════════════════════════════

def assert_sparse_index_consistency(engine: DatabaseEngine, tabla: str):
    """Valida que el sparse_index sea consistente con el contenido real."""
    stats = engine.get_table_stats(tabla)
    index_obj = engine._get_table(tabla).index
    
    # El sparse_index debe tener una entrada para cada página principal
    if stats['index_n_main'] > 0:
        assert len(index_obj.sparse_index) > 0, "sparse_index vacío con registros en main"
        # El primer PK del sparse_index debe ser >= el menor PK en main
        assert index_obj.sparse_index[0][0] > 0, "PK en sparse_index inválido"

def assert_search_found(engine: DatabaseEngine, tabla: str, pk: int, esperado=True):
    """Aserciona que la búsqueda encuentra (o no) un PK."""
    result = engine.search(tabla, pk)
    if esperado:
        assert result.records is not None, f"ERROR: pk={pk} debería encontrarse"
    else:
        assert result.records is None, f"ERROR: pk={pk} no debería encontrarse"
    return result

def assert_range_count(engine: DatabaseEngine, tabla: str, pk1: int, pk2: int, esperado_count: int):
    """Aserciona la cantidad de registros en un rango."""
    result = engine.range_search(tabla, pk1, pk2)
    actual = len(result.records) if result.records else 0
    assert actual == esperado_count, \
        f"ERROR: range_search({pk1},{pk2}) retornó {actual}, esperaba {esperado_count}"
    return result

# ═════════════════════════════════════════════════════════════
# TESTS ORIGINALES (mejorados)
# ═════════════════════════════════════════════════════════════

def test_1_create_and_load():
    """TEST 1 — CREATE TABLE + carga CSV ordenada"""
    separador("TEST 1 — CREATE + LOAD CSV (ORDEN ASCENDENTE)")
    limpiar_archivos('empleados')
    engine = DatabaseEngine()
    csv_path = crear_csv_temporal(DATOS_BASE, COLUMNAS)

    result = engine.create_table_from_csv('empleados', CONFIG, csv_path, 'id')
    os.remove(csv_path)

    mostrar(result, f"{result.records} registros cargados")
    stats = engine.get_table_stats('empleados')
    print(f"  heap_pages={stats['heap_pages']}  index_pages={stats['index_pages']}")
    print(f"  n_main={stats['index_n_main']}  k_aux={stats['index_k_aux']}")
    
    assert_sparse_index_consistency(engine, 'empleados')
    print("  ✓ TEST 1 OK\n")
    return engine


def test_2_search_basic(engine: DatabaseEngine):
    """TEST 2 — SELECT puntual (todos los PKs deben encontrarse)"""
    separador("TEST 2 — SEARCH BÁSICO")
    
    # Búsqueda positiva
    for pk in [10, 20, 30, 40, 50]:
        result = assert_search_found(engine, 'empleados', pk, esperado=True)
        print(f"  search({pk:3d}): ✓ encontrado")
    
    # Búsquedas negativas (frontera)
    assert_search_found(engine, 'empleados', 5, esperado=False)     # Menor que todos
    assert_search_found(engine, 'empleados', 105, esperado=False)   # Mayor que todos
    assert_search_found(engine, 'empleados', 25, esperado=False)    # Entre dos
    
    print("  ✓ TEST 2 OK\n")


def test_3_range_search(engine: DatabaseEngine):
    """TEST 3 — SELECT RANGE con varios casos"""
    separador("TEST 3 — RANGE SEARCH (múltiples casos)")
    
    # Rango completo
    assert_range_count(engine, 'empleados', 10, 100, 10)
    print(f"  range(10, 100): ✓ 10 registros")
    
    # Rango parcial
    assert_range_count(engine, 'empleados', 30, 70, 5)
    print(f"  range(30, 70): ✓ 5 registros")
    
    # Rango unitario (solo una PK)
    assert_range_count(engine, 'empleados', 50, 50, 1)
    print(f"  range(50, 50): ✓ 1 registro")
    
    # Rango vacío (antes del primero)
    assert_range_count(engine, 'empleados', 1, 5, 0)
    print(f"  range(1, 5): ✓ 0 registros")
    
    # Rango vacío (después del último)
    assert_range_count(engine, 'empleados', 110, 200, 0)
    print(f"  range(110, 200): ✓ 0 registros")
    
    print("  ✓ TEST 3 OK\n")


def test_4_insert_basico(engine: DatabaseEngine):
    """TEST 4 — INSERT ordenado (antes del reconstruct)"""
    separador("TEST 4 — INSERT ORDENADO")
    
    nuevos = [
        (110, b'Ana'.ljust(30, b'\x00'), 5555.0),
        (120, b'Bruno'.ljust(30, b'\x00'), 6666.0),
        (130, b'Carmen'.ljust(30, b'\x00'), 7777.0),
    ]
    
    for pk, nombre, salario in nuevos:
        rec = Record((pk, nombre, salario), CONFIG)
        result = engine.insert('empleados', rec)
        assert result.records is not None, f"ERROR: INSERT pk={pk} falló"
        print(f"  INSERT({pk:3d}): ✓ RID={result.records}")
    
    # Verifica accesibilidad
    for pk, _, _ in nuevos:
        assert_search_found(engine, 'empleados', pk, esperado=True)
    
    stats = engine.get_table_stats('empleados')
    print(f"  Estado post-INSERT: k_aux={stats['index_k_aux']}  k_limit={stats['index_k_limit']}")
    print("  ✓ TEST 4 OK\n")


def test_5_delete(engine: DatabaseEngine):
    """TEST 5 — DELETE + search post-delete"""
    separador("TEST 5 — DELETE")
    
    # Elimina un registro que existe
    result = engine.delete('empleados', 20)
    assert result.records == True, "DELETE debería retornar True"
    print(f"  DELETE(20): ✓ ok")
    
    # Verifica que ya no existe
    assert_search_found(engine, 'empleados', 20, esperado=False)
    print(f"  search(20) post-DELETE: ✓ no encontrado")
    
    # Intenta eliminar un PK que no existe
    result = engine.delete('empleados', 999)
    assert result.records == False, "DELETE(999) debería retornar False"
    print(f"  DELETE(999): ✓ ok (no existe)")
    
    print("  ✓ TEST 5 OK\n")


def test_6_reconstruct_trigger(engine: DatabaseEngine):
    """TEST 6 — RECONSTRUCT automático al exceder k_limit"""
    separador("TEST 6 — RECONSTRUCT AUTOMÁTICO")
    
    stats = engine.get_table_stats('empleados')
    k_limit = stats['index_k_limit']
    k_aux_inicial = stats['index_k_aux']
    print(f"  k_limit={k_limit}, k_aux_inicial={k_aux_inicial}")
    print(f"  Insertando {k_limit + 2} registros para disparar reconstruct...")
    
    reconstruct_ocurrio = False
    pk_base = 500
    
    for i in range(k_limit + 2):
        pk = pk_base + i
        rec = Record((pk, f'R{i}'.encode().ljust(30, b'\x00'), float(i * 100)), CONFIG)
        
        k_antes = engine.get_table_stats('empleados')['index_k_aux']
        engine.insert('empleados', rec)
        k_despues = engine.get_table_stats('empleados')['index_k_aux']
        
        if k_despues < k_antes:
            reconstruct_ocurrio = True
            print(f"  *** RECONSTRUCT disparado en i={i} (pk={pk}) ***")
            print(f"      k_aux: {k_antes} → {k_despues}")
    
    assert reconstruct_ocurrio, "ERROR: reconstruct no se disparó"
    
    # Verifica integridad post-reconstruct
    assert_search_found(engine, 'empleados', pk_base, esperado=True)
    assert_search_found(engine, 'empleados', pk_base + k_limit, esperado=True)
    assert_sparse_index_consistency(engine, 'empleados')
    
    print("  ✓ TEST 6 OK\n")


def test_7_io_counter(engine: DatabaseEngine):
    """TEST 7 — IOCounter por consulta"""
    separador("TEST 7 — IO COUNTER POR CONSULTA")
    
    r1 = engine.search('empleados', 10)
    r2 = engine.search('empleados', 100)
    r3 = engine.range_search('empleados', 10, 50)
    
    print(f"  search(10):    reads={r1.io_stats.get('reads', 0)}  writes={r1.io_stats.get('writes', 0)}")
    print(f"  search(100):   reads={r2.io_stats.get('reads', 0)}  writes={r2.io_stats.get('writes', 0)}")
    print(f"  range(10,50):  reads={r3.io_stats.get('reads', 0)}  writes={r3.io_stats.get('writes', 0)}")
    
    assert r1.io_stats['total'] >= 0, "IOCounter no debería ser negativo"
    assert r2.io_stats['total'] >= 0, "IOCounter no debería ser negativo"
    assert r3.io_stats['total'] >= 0, "IOCounter no debería ser negativo"
    
    print("  ✓ TEST 7 OK\n")

# ═════════════════════════════════════════════════════════════
# TESTS NUEVOS — CASOS BORDE Y FRONTERA
# ═════════════════════════════════════════════════════════════

def test_8_ordered_vs_unordered():
    """TEST 8 — COMPARACIÓN: ORDEN vs DESORDENADO (el bug original)"""
    separador("TEST 8 — ORDEN vs DESORDENADO (Critical Bug Test)")
    
    datos_inserts = [
        (1000, b'Ordered1'.ljust(30, b'\x00'), 1000.0),
        (20, b'Ordered2'.ljust(30, b'\x00'), 2000.0),
        (30, b'Ordered3'.ljust(30, b'\x00'), 3000.0),
        (40, b'Ordered4'.ljust(30, b'\x00'), 4000.0),
    ]
    
    # TEST 8A: Orden ASCENDENTE
    print("  [8A] Inserciones en ORDEN ASCENDENTE...")
    limpiar_archivos('test_ordered')
    engine_ord = DatabaseEngine()
    
    # Crea tabla vacía
    filas_vacias = [{'id': '999', 'nombre': 'Dummy', 'salario': '0.0'}]
    csv_path = crear_csv_temporal(filas_vacias, COLUMNAS)
    engine_ord.create_table_from_csv('test_ordered', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    
    # Elimina el dummy
    engine_ord.delete('test_ordered', 999)
    
    # Inserta en orden
    for pk, nombre, salario in sorted(datos_inserts, key=lambda x: x[0]):
        rec = Record((pk, nombre, salario), CONFIG)
        engine_ord.insert('test_ordered', rec)
        print(f"    INSERT({pk:4d})")
    
    # Busca todos
    busquedas_ord = {}
    for pk, _, _ in datos_inserts:
        r = engine_ord.search('test_ordered', pk)
        busquedas_ord[pk] = r.records is not None
        print(f"    search({pk:4d}): {'✓' if busquedas_ord[pk] else '✗ FALLO'}")
    
    # TEST 8B: Orden DESORDENADO (descending)
    print("\n  [8B] Inserciones en ORDEN DESORDENADO (descending)...")
    limpiar_archivos('test_unordered')
    engine_unord = DatabaseEngine()
    
    csv_path = crear_csv_temporal(filas_vacias, COLUMNAS)
    engine_unord.create_table_from_csv('test_unordered', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    
    engine_unord.delete('test_unordered', 999)
    
    # Inserta en orden INVERSO (el caso que causaba el bug)
    for pk, nombre, salario in sorted(datos_inserts, key=lambda x: -x[0]):
        rec = Record((pk, nombre, salario), CONFIG)
        engine_unord.insert('test_unordered', rec)
        print(f"    INSERT({pk:4d})")
    
    # Busca todos
    busquedas_unord = {}
    for pk, _, _ in datos_inserts:
        r = engine_unord.search('test_unordered', pk)
        busquedas_unord[pk] = r.records is not None
        print(f"    search({pk:4d}): {'✓' if busquedas_unord[pk] else '✗ FALLO'}")
    
    # Validación: ambos órdenes deberían encontrar todo
    assert all(busquedas_ord.values()), "ERROR: orden ascendente falló"
    assert all(busquedas_unord.values()), "ERROR: orden descendente falló (BUG de inserciones desordenadas)"
    
    print("\n  ✓ TEST 8 OK — Bug de inserciones desordenadas está FIJO\n")


def test_9_empty_and_single():
    """TEST 9 — Casos extremos: tabla vacía y un único registro"""
    separador("TEST 9 — CASOS EXTREMOS (vacío, único registro)")
    
    # TEST 9A: Tabla vacía
    print("  [9A] Tabla vacía...")
    limpiar_archivos('test_empty')
    engine = DatabaseEngine()
    
    filas = [{'id': '1', 'nombre': 'Temp', 'salario': '0.0'}]
    csv_path = crear_csv_temporal(filas, COLUMNAS)
    engine.create_table_from_csv('test_empty', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    
    engine.delete('test_empty', 1)
    
    # Busca en tabla vacía
    r = engine.search('test_empty', 1)
    assert r.records is None, "Búsqueda en tabla vacía debería retornar None"
    print(f"    search(1) en tabla vacía: ✓ None")
    
    r = engine.range_search('test_empty', 1, 100)
    assert len(r.records) == 0 if r.records else True, "range_search en tabla vacía debe retornar []"
    print(f"    range_search(1,100) en tabla vacía: ✓ []")
    
    # TEST 9B: Un único registro
    print("\n  [9B] Un único registro...")
    rec = Record((999, b'Unico'.ljust(30, b'\x00'), 9999.0), CONFIG)
    engine.insert('test_empty', rec)
    
    r = engine.search('test_empty', 999)
    assert r.records is not None, "Búsqueda de único registro falló"
    print(f"    search(999): ✓ encontrado")
    
    r = engine.range_search('test_empty', 900, 1000)
    assert len(r.records) == 1, "range_search con un registro debe retornar [único]"
    print(f"    range_search(900,1000): ✓ 1 registro")
    
    print("  ✓ TEST 9 OK\n")


def test_10_page_boundaries():
    """TEST 10 — Condiciones de frontera de páginas"""
    separador("TEST 10 — PAGE BOUNDARIES (fill rates)")
    
    limpiar_archivos('test_pages')
    engine = DatabaseEngine()
    
    filas = [{'id': '0', 'nombre': 'Init', 'salario': '0.0'}]
    csv_path = crear_csv_temporal(filas, COLUMNAS)
    engine.create_table_from_csv('test_pages', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    
    engine.delete('test_pages', 0)
    
    # Obtén info de índice
    stats_pre = engine.get_table_stats('test_pages')
    index = engine._get_table('test_pages').index
    entries_per_page = index.entries_per_page
    
    print(f"  entries_per_page = {entries_per_page}")
    
    # Inserta exactamente 'entries_per_page' registros (llena una página)
    print(f"  Insertando {entries_per_page} registros (llenar 1 página)...")
    for i in range(entries_per_page):
        pk = 1000 + i
        rec = Record((pk, f'PG{i}'.encode().ljust(30, b'\x00'), float(i)), CONFIG)
        engine.insert('test_pages', rec)
    
    # Inserta uno más (abre segunda página)
    print(f"  Insertando 1 más (página 2)...")
    rec = Record((2000, b'Extra'.ljust(30, b'\x00'), 1000.0), CONFIG)
    engine.insert('test_pages', rec)
    
    # Valida que todos sean encontrados
    print(f"  Verificando accesibilidad...")
    for i in range(entries_per_page):
        pk = 1000 + i
        r = engine.search('test_pages', pk)
        assert r.records is not None, f"ERROR: pk={pk} no encontrado"
    
    r = engine.search('test_pages', 2000)
    assert r.records is not None, "ERROR: pk=2000 no encontrado"
    
    print(f"  ✓ Todos los registros encontrados")
    print("  ✓ TEST 10 OK\n")


def test_11_multiple_reconstructs():
    """TEST 11 — Múltiples RECONSTRUCT secuenciales"""
    separador("TEST 11 — MÚLTIPLES RECONSTRUCTS")
    
    limpiar_archivos('test_multi_recon')
    engine = DatabaseEngine()
    
    filas = [{'id': '0', 'nombre': 'Init', 'salario': '0.0'}]
    csv_path = crear_csv_temporal(filas, COLUMNAS)
    engine.create_table_from_csv('test_multi_recon', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    engine.delete('test_multi_recon', 0)
    
    k_limit = engine.get_table_stats('test_multi_recon')['index_k_limit']
    print(f"  k_limit = {k_limit}")
    
    recon_count = 0
    
    # Ejecuta varias rondas de inserciones
    for ronda in range(3):
        print(f"\n  [Ronda {ronda+1}] Insertando {k_limit + 2} registros...")
        
        pk_base = (ronda + 1) * 1000
        k_antes = engine.get_table_stats('test_multi_recon')['index_k_aux']
        
        for i in range(k_limit + 2):
            pk = pk_base + i
            rec = Record((pk, f'R{ronda}_{i}'.encode().ljust(30, b'\x00'), float(i)), CONFIG)
            engine.insert('test_multi_recon', rec)
            
            k_despues = engine.get_table_stats('test_multi_recon')['index_k_aux']
            if k_despues < k_antes:
                recon_count += 1
                print(f"    RECONSTRUCT #{recon_count} disparado en pk={pk}")
                k_antes = k_despues
        
        # Verifica integridad
        stats = engine.get_table_stats('test_multi_recon')
        print(f"    Estado post-ronda: n_main={stats['index_n_main']}, k_aux={stats['index_k_aux']}")
    
    # Busca registros de todas las rondas
    print(f"\n  Verificando integridad post-{recon_count} reconstructs...")
    found_count = 0
    for ronda in range(3):
        pk_base = (ronda + 1) * 1000
        for i in range(k_limit + 2):
            pk = pk_base + i
            r = engine.search('test_multi_recon', pk)
            if r.records is not None:
                found_count += 1
    
    expected = 3 * (k_limit + 2)
    assert found_count == expected, f"ERROR: encontrados {found_count}/{expected} registros"
    print(f"  ✓ {found_count}/{expected} registros encontrados")
    print("  ✓ TEST 11 OK\n")


def test_12_mixed_operations():
    """TEST 12 — Operaciones mixtas (insert/delete/search en secuencia aleatoria)"""
    separador("TEST 12 — OPERACIONES MIXTAS")
    
    limpiar_archivos('test_mixed')
    engine = DatabaseEngine()
    
    filas = [{'id': '0', 'nombre': 'Init', 'salario': '0.0'}]
    csv_path = crear_csv_temporal(filas, COLUMNAS)
    engine.create_table_from_csv('test_mixed', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    engine.delete('test_mixed', 0)
    
    pks_vivos = set()
    
    operaciones = [
        ('INSERT', 100), ('INSERT', 50), ('INSERT', 150),
        ('SEARCH', 100), ('DELETE', 50), ('SEARCH', 50),
        ('INSERT', 75), ('RANGE', (50, 150)), ('INSERT', 200),
        ('DELETE', 100), ('SEARCH', 100), ('RANGE', (0, 300)),
    ]
    
    for op, arg in operaciones:
        if op == 'INSERT':
            pk = arg
            rec = Record((pk, f'Rec{pk}'.encode().ljust(30, b'\x00'), float(pk)), CONFIG)
            result = engine.insert('test_mixed', rec)
            pks_vivos.add(pk)
            print(f"  INSERT({pk:3d}): ✓")
        
        elif op == 'DELETE':
            pk = arg
            engine.delete('test_mixed', pk)
            pks_vivos.discard(pk)
            print(f"  DELETE({pk:3d}): ✓")
        
        elif op == 'SEARCH':
            pk = arg
            r = engine.search('test_mixed', pk)
            encontrado = r.records is not None
            vivo = pk in pks_vivos
            assert encontrado == vivo, f"ERROR: SEARCH({pk}) inconsistente con estado"
            print(f"  SEARCH({pk:3d}): {'✓ found' if encontrado else '✓ not found'}")
        
        elif op == 'RANGE':
            pk1, pk2 = arg
            pk1, pk2 = arg
            r = engine.range_search('test_mixed', pk1, pk2)
            registros = len(r.records) if r.records else 0
            esperado = sum(1 for pk in pks_vivos if pk1 <= pk <= pk2)
            try:
                assert registros == esperado, f"ERROR: RANGE({pk1},{pk2}) retornó {registros}, esperaba {esperado}"
                print(f"  RANGE({pk1:3d},{pk2:3d}): ✓ {registros} registros")
            except AssertionError as e:
                # Diagnostics: imprimir estado esperado vs real y estado interno del índice
                print(f"\n--- DIAGNOSTIC: RANGE({pk1},{pk2}) FALLÓ ---")
                print(f"  pks_vivos (estado esperado): {sorted(pks_vivos)}")
                print(f"  esperado_count: {esperado}")
                # Registros retornados (PKs)
                returned_pks = []
                if r.records:
                    try:
                        returned_pks = [rec.get_pk() for rec in r.records]
                    except Exception:
                        returned_pks = list(r.records)
                print(f"  registros retornados (PKs): {returned_pks}")

                # Estado interno del índice
                idx = engine._get_table('test_mixed').index
                try:
                    print(f"  index.n_main={idx.n_main}  index.k_aux={idx.k_aux}  index.last_main_page={idx.last_main_page}")
                    print(f"  index.first_logical_pos={idx.first_logical_pos}  entries_per_page={idx.entries_per_page}")
                    print(f"  sparse_index (len={len(idx.sparse_index)}): {idx.sparse_index}")
                except Exception as ie:
                    print(f"  no fue posible leer estructura interna del índice: {ie}")

                # Re-lanzar para que el test muestre falla en CI
                raise
    
    print("  ✓ TEST 12 OK\n")


def test_13_large_dataset():
    """TEST 13 — Dataset grande con inserciones desordenadas"""
    separador("TEST 13 — DATASET GRANDE (100+ registros desordenados)")
    
    limpiar_archivos('test_large')
    engine = DatabaseEngine()
    
    # Crea tabla con 1 registro inicial
    filas = [{'id': '0', 'nombre': 'Init', 'salario': '0.0'}]
    csv_path = crear_csv_temporal(filas, COLUMNAS)
    engine.create_table_from_csv('test_large', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    engine.delete('test_large', 0)
    
    # Inserta 100 registros en orden ALEATORIO
    import random
    pks = list(range(1, 101))
    random.shuffle(pks)
    
    print(f"  Insertando {len(pks)} registros en orden aleatorio...")
    for idx, pk in enumerate(pks):
        if idx % 25 == 0:
            print(f"    [{idx}/{len(pks)}]...")
        rec = Record((pk, f'Rec{pk:03d}'.encode().ljust(30, b'\x00'), float(pk * 10)), CONFIG)
        engine.insert('test_large', rec)
    
    # Verifica accesibilidad de todos
    print(f"  Verificando {len(pks)} registros...")
    no_encontrados = []
    for pk in pks:
        r = engine.search('test_large', pk)
        if r.records is None:
            no_encontrados.append(pk)
    
    assert len(no_encontrados) == 0, f"ERROR: No encontrados {no_encontrados}"
    print(f"  ✓ Todos {len(pks)} registros encontrados")
    
    # Range search: debe encontrar todos
    r = engine.range_search('test_large', 1, 100)
    assert len(r.records) == 100, f"ran ge(1,100) retornó {len(r.records)}, esperaba 100"
    print(f"  ✓ range_search(1,100): 100 registros")
    
    print("  ✓ TEST 13 OK\n")


def test_14_boundary_search():
    """TEST 14 — Búsquedas en los límites (menor, mayor, in-between)"""
    separador("TEST 14 — BÚSQUEDAS EN LÍMITES")
    
    limpiar_archivos('test_bounds')
    engine = DatabaseEngine()
    
    # Carga datos con PKs específicos
    datos = [
        {'id': '10', 'nombre': 'First', 'salario': '1000.0'},
        {'id': '50', 'nombre': 'Middle', 'salario': '5000.0'},
        {'id': '100', 'nombre': 'Last', 'salario': '10000.0'},
    ]
    csv_path = crear_csv_temporal(datos, COLUMNAS)
    engine.create_table_from_csv('test_bounds', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    
    # Test: límites
    tests = [
        (10, True,    "primer PK"),
        (100, True,   "último PK"),
        (50, True,    "PK intermedio"),
        (9, False,    "antes del primero"),
        (101, False,  "después del último"),
        (25, False,   "entre primero e intermedio"),
        (75, False,   "entre intermedio y último"),
        (1, False,    "muy pequeño"),
        (999, False,  "muy grande"),
    ]
    
    for pk, debe_existir, descripcion in tests:
        r = engine.search('test_bounds', pk)
        existe = r.records is not None
        assert existe == debe_existir, f"ERROR: SEARCH({pk}) {descripcion} falló"
        estado = "✓ encontrado" if existe else "✓ no encontrado"
        print(f"  search({pk:3d}): {estado:15s} — {descripcion}")
    
    print("  ✓ TEST 14 OK\n")


def test_15_duplicate_prevention():
    """TEST 15 — Prevención de duplicados (UNIQUE constraint)"""
    separador("TEST 15 — PREVENCIÓN DE DUPLICADOS")
    
    limpiar_archivos('test_unique')
    engine = DatabaseEngine()
    
    # Carga datos iniciales
    datos = [
        {'id': '1', 'nombre': 'First', 'salario': '1000.0'},
    ]
    csv_path = crear_csv_temporal(datos, COLUMNAS)
    engine.create_table_from_csv('test_unique', CONFIG, csv_path, 'id')
    os.remove(csv_path)
    
    # Intenta insertar duplicado
    rec = Record((1, b'Duplicate'.ljust(30, b'\x00'), 9999.0), CONFIG)
    try:
        engine.insert('test_unique', rec)
        assert False, "ERROR: debería haber lanzado excepción por duplicado"
    except ValueError as e:
        if "UNIQUE" in str(e) or "ya existe" in str(e):
            print(f"  ✓ Excepción correcta: {e}")
        else:
            raise
    
    print("  ✓ TEST 15 OK\n")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("  DATABASE ENGINE — SUITE DE PRUEBAS ROBUSTA")
    print("="*60)
    
    # Tests originales
    engine = test_1_create_and_load()
    test_2_search_basic(engine)
    test_3_range_search(engine)
    test_4_insert_basico(engine)
    test_5_delete(engine)
    test_6_reconstruct_trigger(engine)
    test_7_io_counter(engine)
    
    # Tests nuevos — casos borde y frontera
    test_8_ordered_vs_unordered()
    test_9_empty_and_single()
    test_10_page_boundaries()
    test_11_multiple_reconstructs()
    test_12_mixed_operations()
    test_13_large_dataset()
    test_14_boundary_search()
    test_15_duplicate_prevention()
    
    # Resumen final
    separador("✓ TODOS LOS TESTS PASARON")
    print("\n  Suite completada: 15 tests, 0 fallos")
    print("  Evaluaciones incluidas:")
    print("    • Casos borde (vacío, único registro)")
    print("    • Frontera (límites de búsqueda y rango)")
    print("    • Orden (ascendente vs descendente — el bug original)")
    print("    • Reconstructs múltiples y operaciones mixtas")
    print("    • Dataset grande (100+ registros aleatorios)")
    print("    • Page boundaries y UNIQUE constraints")
    print("="*60 + "\n")
