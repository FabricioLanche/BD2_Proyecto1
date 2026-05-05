import csv
import time
import sys
import os
import tempfile
import glob
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database_engine import DatabaseEngine
from organization.data_structures import TableConfig, Record

def test_large_dataset_100k():
    print("\n" + "="*70)
    print("  TEST DATASET REAL — 100k+ CIUDADES")
    print("="*70)

    for f in glob.glob("cities*.idx*") + glob.glob("cities*.heap*"):
        try:
            os.remove(f)
        except:
            pass
    engine = DatabaseEngine()
    
    # Configurar tabla con estructura del CSV
    # Formato: id(int) name(50s) state_id(int) state_code(3s) state_name(30s)
    #          country_id(int) country_code(2s) country_name(30s) latitude(f) longitude(f) wikiDataId(20s)
    CONFIG = TableConfig(
        data_format='<i50si3s30si2s30sff20s',
        column_names=['id', 'name', 'state_id', 'state_code', 'state_name', 
                      'country_id', 'country_code', 'country_name', 'latitude', 'longitude', 'wikiDataId']
    )
    
    csv_path = 'cities.csv'
    
  
    print("\n[FASE 1] CREANDO TABLA Y CARGANDO CSV...")
    print(f"  Archivo: {csv_path}")
    
    t0 = time.time()
    result = engine.create_table_from_csv('cities', CONFIG, csv_path, 'id')
    t_load = time.time() - t0
    
    # Obtener estadísticas
    entry = engine._get_table('cities')
    index = entry.index
    heap = entry.heap
    io_counter = entry.io_counter
    
    print(f"  ✓ Tabla creada y cargada en {t_load:.2f}s")
    print(f"  Registros indexados: {index.n_main}")
    print(f"  Páginas heap: {heap.last_page_id + 1}")
    print(f"  Páginas índice (main): {index.last_main_page}")
    print(f"  I/O Reads: {io_counter.reads} | Writes: {io_counter.writes} | Total: {io_counter.reads + io_counter.writes}")
    

    print("\n[FASE 2] BÚSQUEDAS SIMPLES (EXACTAS)...")
    
    # Prueba 1: Búscar primeros registros
    test_ids = [52, 68, 78, 84, 115]
    io_counter.reset()
    t0 = time.time()
    
    for test_id in test_ids:
        result_search = engine.search('cities', test_id)
        if result_search.records is not None:
            record = result_search.records
            print(f"  search({test_id}): ✓ encontrado → {record.get_attribute('name')} ({record.get_attribute('latitude')}, {record.get_attribute('longitude')})")
        else:
            print(f"  search({test_id}): ✗ NO ENCONTRADO")
    
    t_search = time.time() - t0
    print(f"  Tiempo: {t_search*1000:.2f}ms | I/O reads: {io_counter.reads}")
    
    # Prueba 2: Búscar a registros aleatorios (sampleo)
    print(f"\n  Buscando registros aleatorios...")
    io_counter.reset()
    t0 = time.time()
    sample_ids = [100, 500, 1000, 5000, 10000]
    found = 0
    for sid in sample_ids:
        if engine.search('cities', sid).records is not None:
            found += 1
    t_sample = time.time() - t0
    print(f"  Encontrados: {found}/{len(sample_ids)} | Tiempo: {t_sample*1000:.2f}ms | I/O: {io_counter.reads}")
    
 
    print("\n[FASE 3] RANGE SEARCHES...")
    
    test_ranges = [
        (50, 100),
        (1000, 2000),
        (10000, 10100),
        (50000, 50500),
    ]
    
    for pk1, pk2 in test_ranges:
        io_counter.reset()
        t0 = time.time()
        result_range = engine.range_search('cities', pk1, pk2)
        t_range = time.time() - t0
        
        count = len(result_range.records) if result_range.records else 0
        print(f"  range({pk1:6d}, {pk2:6d}): {count:5d} registros | {t_range*1000:7.2f}ms | I/O: {io_counter.reads:4d}")
    
    print("\n[FASE 4] PRUEBA DE MODIFICACIÓN (muestra de 10 deletes)...")
    
    io_counter.reset()
    t0 = time.time()
    
    delete_ids = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
    for del_id in delete_ids:
        engine.delete('cities', del_id)
    
    t_delete = time.time() - t0
    print(f"  ✓ {len(delete_ids)} deletes en {t_delete*1000:.2f}ms")
    print(f"  I/O writes: {io_counter.writes}")
    
    # Verificar que se eliminaron
    io_counter.reset()
    found_count = 0
    for del_id in delete_ids:
        if engine.search('cities', del_id).records is not None:
            found_count += 1
    
    print(f"  Verificación: {len(delete_ids) - found_count}/{len(delete_ids)} realmente eliminados")
    
 
    print("\n[FASE 5] PRUEBA DE INSERCIÓN (muestra de 5 registros)...")
    
    new_records = [
    Record((
        300001,
        'Test City 1'.encode('utf-8').ljust(50, b'\x00'),           # 50s
        9999,
        'TST'.encode('utf-8').ljust(3, b'\x00'),                    # 3s
        'Test State'.encode('utf-8').ljust(30, b'\x00'),            # 30s
        999,
        'TS'.encode('utf-8').ljust(2, b'\x00'),                     # 2s
        'Test Country'.encode('utf-8').ljust(30, b'\x00'),          # 30s
        0.0,
        0.0,
        'Q999999'.encode('utf-8').ljust(20, b'\x00')                # 20s
    ), CONFIG),
    Record((
        300002,
        'Test City 2'.encode('utf-8').ljust(50, b'\x00'),
        9999,
        'TST'.encode('utf-8').ljust(3, b'\x00'),
        'Test State'.encode('utf-8').ljust(30, b'\x00'),
        999,
        'TS'.encode('utf-8').ljust(2, b'\x00'),
        'Test Country'.encode('utf-8').ljust(30, b'\x00'),
        1.0,
        1.0,
        'Q999998'.encode('utf-8').ljust(20, b'\x00')
    ), CONFIG),
    Record((
        300003,
        'Test City 3'.encode('utf-8').ljust(50, b'\x00'),
        9999,
        'TST'.encode('utf-8').ljust(3, b'\x00'),
        'Test State'.encode('utf-8').ljust(30, b'\x00'),
        999,
        'TS'.encode('utf-8').ljust(2, b'\x00'),
        'Test Country'.encode('utf-8').ljust(30, b'\x00'),
        2.0,
        2.0,
        'Q999997'.encode('utf-8').ljust(20, b'\x00')
    ), CONFIG),
    Record((
        300004,
        'Test City 4'.encode('utf-8').ljust(50, b'\x00'),
        9999,
        'TST'.encode('utf-8').ljust(3, b'\x00'),
        'Test State'.encode('utf-8').ljust(30, b'\x00'),
        999,
        'TS'.encode('utf-8').ljust(2, b'\x00'),
        'Test Country'.encode('utf-8').ljust(30, b'\x00'),
        3.0,
        3.0,
        'Q999996'.encode('utf-8').ljust(20, b'\x00')
    ), CONFIG),
    Record((
        300005,
        'Test City 5'.encode('utf-8').ljust(50, b'\x00'),
        9999,
        'TST'.encode('utf-8').ljust(3, b'\x00'),
        'Test State'.encode('utf-8').ljust(30, b'\x00'),
        999,
        'TS'.encode('utf-8').ljust(2, b'\x00'),
        'Test Country'.encode('utf-8').ljust(30, b'\x00'),
        4.0,
        4.0,
        'Q999995'.encode('utf-8').ljust(20, b'\x00')
    ), CONFIG),
    ]
    io_counter.reset()
    t0 = time.time()
    
    for rec in new_records:
        engine.insert('cities', rec)
    
    t_insert = time.time() - t0
    print(f"  ✓ {len(new_records)} inserts en {t_insert*1000:.2f}ms")
    print(f"  I/O operations: {io_counter.reads + io_counter.writes}")
    
    # Verificar que se insertaron
    io_counter.reset()
    found = 0
    for rec in new_records:
        if engine.search('cities', rec.get_pk()).records is not None:
            found += 1
    print(f"  Verificación: {found}/{len(new_records)} encontrados después de insert")
    
    print("\n" + "="*70)
    print("  RESUMEN FINAL")
    print("="*70)
    print(f"  Registros en sistema:  {index.n_main}")
    print(f"  Registros en auxiliar: {index.k_aux}")
    print(f"  Páginas heap usadas:   {heap.last_page_id + 1}")
    print(f"  Páginas índice:        {index.last_main_page}")
    print(f"  Tiempo total carga:    {t_load:.2f}s")
    print(f"  Estado: ✓ TEST COMPLETADO EXITOSAMENTE")
    print("="*70 + "\n")

if __name__ == '__main__':
    test_large_dataset_100k()