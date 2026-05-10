
import os
import sys
import time
import random
import csv
import shutil
import struct
import pandas as pd
import numpy as np

import matplotlib
matplotlib.use('Agg')  # Non-GUI backend para evitar problemas en servidores
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns

from pathlib import Path
from typing import Dict, List, Tuple, Optional, Callable
from tabulate import tabulate

# Agregar path para importar Backend
sys.path.insert(0, str(Path(__file__).parent.parent))

from Backend.DBMS.database_engine import DatabaseEngine, QueryResult
from Backend.DBMS.organization.data_structures import TableConfig, Record
from Backend.DBMS.organization.page_manager import PageManager, IOCounter
from Backend.DBMS.organization.buffer_manager import BufferManager, PageLockStats
from Backend.DBMS.LockManager import LockManager
from Backend.DBMS.utils.path_utils import resolve_data_path



# ============================================================================
# CONFIGURACIÓN GLOBAL
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
CSV_PATH = SCRIPT_DIR / "cities.csv"
RESULTS_DIR = SCRIPT_DIR / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
ENGINE_DATA_DIR = Path(resolve_data_path("engine_data_probe.tmp")).parent

# ✓ MEJORADO: Validación robusta de directorios
def ensure_directories():
    """Crea directorios con validación de permisos"""
    dirs = [DATA_DIR, RESULTS_DIR, PLOTS_DIR]
    for dir_path in dirs:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            # Verificar que podemos escribir
            test_file = dir_path / ".write_test"
            test_file.touch()
            test_file.unlink()
            print(f"✓ Directorio accesible: {dir_path}")
        except Exception as e:
            print(f"✗ ERROR - No se puede acceder a {dir_path}: {e}")
            raise

ensure_directories()
os.chdir(DATA_DIR)

# Configuración de tabla para cities.csv
CONFIG = TableConfig(
    data_format='<i50si3s30si2s30sff20s',
    column_names=[
        'id', 'name', 'state_id', 'state_code', 'state_name',
        'country_id', 'country_code', 'country_name', 'latitude', 'longitude', 'wikiDataId'
    ],
    pk_col_name='id'
)

# Estilos de gráficas
sns.set_style("whitegrid")
COLORS = {
    'sequential': '#2196F3',
    'hashing': '#4CAF50',
    'btree': '#FF9800',
    'rtree': '#E91E63',
    'without_buffer': '#EF5350',
    'with_buffer_cold': '#42A5F5',
    'with_buffer_warm': '#1976D2'
}



# ============================================================================
# FUNCIONES HELPER - NÚCLEO DEL SISTEMA
# ============================================================================

def crear_csv_temporal_n(csv_path: Path, n: int, output_path: Path) -> Path:
    """Crea un CSV temporal con solo los primeros n registros."""
    with open(csv_path, 'r', encoding='utf-8') as f_in:
        with open(output_path, 'w', encoding='utf-8', newline='') as f_out:
            reader = csv.reader(f_in)
            writer = csv.writer(f_out)
            header = next(reader)
            writer.writerow(header)
            for i, row in enumerate(reader):
                if i >= n:
                    break
                writer.writerow(row)
    return output_path


def limpiar_archivos_tabla(table_name: str) -> None:
    """Elimina los archivos físicos que crea el motor para una tabla."""
    for candidate in ENGINE_DATA_DIR.glob(f"{table_name}*"):
        if candidate.is_file():
            try:
                candidate.unlink()
            except Exception as e:
                print(f"⚠ No se pudo eliminar {candidate}: {e}")


def invalidar_cache_y_resetear(engine: DatabaseEngine, table_name: str) -> None:
    """
    Invalida caché (BufferManager + PageManager subyacente) y resetea contadores IO.
    Garantiza mediciones en disco frío real.
    """
    table_entry = engine._tables[table_name]
    # Invalidar caché del BufferManager
    table_entry.heap_pm.invalidate_cache()
    table_entry.index_pm.invalidate_cache()
    # Invalidar caché interna del PageManager subyacente (mini-caché de 1 página)
    if hasattr(table_entry.heap_pm, 'pm'):
        table_entry.heap_pm.pm.invalidate_cache()
    if hasattr(table_entry.index_pm, 'pm'):
        table_entry.index_pm.pm.invalidate_cache()
    # Invalidar caché de índices secundarios (hash, btree, rtree)
    for h_idx in table_entry.hash_indices.values():
        if hasattr(h_idx, 'pm'):
            h_idx.pm.invalidate_cache()
            if hasattr(h_idx.pm, 'pm'):
                h_idx.pm.pm.invalidate_cache()
    for b_idx in table_entry.btree_indices.values():
        if hasattr(b_idx, 'pm'):
            b_idx.pm.invalidate_cache()
            if hasattr(b_idx.pm, 'pm'):
                b_idx.pm.pm.invalidate_cache()
    if table_entry.rtree and hasattr(table_entry.rtree, 'page_manager'):
        table_entry.rtree.page_manager.invalidate_cache()
        if hasattr(table_entry.rtree.page_manager, 'pm'):
            table_entry.rtree.page_manager.pm.invalidate_cache()
    engine._reset_io(table_entry)


def setup_engine(
    csv_path: Path,
    config: TableConfig,
    pk_col: str,
    spatial_meta: dict,
    n: int,
    table_name: str = "cities",
    hash_meta: list = None,
    btree_meta: list = None
) -> Tuple[DatabaseEngine, List[int], List[Tuple[float, float]], dict]:
    """
    Crea engine limpio, carga n registros y retorna todo.
    
    Returns:
        (engine, pks_disponibles, coords_espaciales, io_insercion)
    """
    if hash_meta is None:
        hash_meta = []
    if btree_meta is None:
        btree_meta = []
        
    limpiar_archivos_tabla(table_name)
    
    # Crear CSV temporal con solo n registros
    tmp_csv = DATA_DIR / f"_tmp_{table_name}_{n}.csv"
    crear_csv_temporal_n(csv_path, n, tmp_csv)
    
    # Crear engine y cargar datos
    engine = DatabaseEngine()
    
    # Extraer PKs y coordenadas del CSV temporal
    pks = []
    coords = []
    with open(tmp_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pks.append(int(row['id']))
                coords.append((float(row['latitude']), float(row['longitude'])))
            except Exception:
                pass
    
    # Crear tabla desde CSV TEMPORAL
    result = engine.create_table_from_csv(
        table_name=table_name,
        config=config,
        csv_path=str(tmp_csv),
        pk_col=pk_col,
        spatial_meta=spatial_meta,
        hash_meta=hash_meta,
        btree_meta=btree_meta,
        page_size=4096
    )
    
    # Limpieza
    try:
        tmp_csv.unlink()
    except:
        pass
    
    # Capturar I/O de inserción
    io_insercion = engine._tables[table_name].io_counter.snapshot()
    
    return engine, pks, coords, io_insercion


def medir_busquedas(
    engine: DatabaseEngine,
    table_name: str,
    metodo_fn: Callable,
    samples: List,
    sample_name: str = "búsqueda",
    n_samples: Optional[int] = None
) -> dict:
    """
    Encapsula el bucle de búsqueda con aislamiento de disco frío.
    """
    if n_samples:
        samples = random.sample(samples, min(n_samples, len(samples)))
    
    metrics = {'reads': 0, 'writes': 0, 'elapsed_ms': 0.0, 'count': 0}
    
    for sample in samples:
        try:
            # Disco frío: invalida caché ANTES de cada búsqueda
            invalidar_cache_y_resetear(engine, table_name)
            
            # Ejecutar búsqueda
            result = metodo_fn(sample)
            if result:
                io_stats = result.io_stats
                # IOCounter.snapshot() retorna {reads, writes, total} plano
                metrics['reads'] += io_stats.get('reads', 0)
                metrics['writes'] += io_stats.get('writes', 0)
                metrics['elapsed_ms'] += result.elapsed_ms
                metrics['count'] += 1
        except Exception as e:
            print(f"⚠ Error en búsqueda ({sample_name}): {e}")
    
    # Promediar
    if metrics['count'] > 0:
        metrics['avg_reads'] = metrics['reads'] / metrics['count']
        metrics['avg_writes'] = metrics['writes'] / metrics['count']
        metrics['reads'] = round(metrics['avg_reads'])
        metrics['writes'] = round(metrics['avg_writes'])
        metrics['elapsed_ms'] = metrics['elapsed_ms'] / metrics['count']
    
    metrics['total'] = metrics['reads'] + metrics['writes']
    del metrics['count']
    
    return metrics


def format_table_results(results: Dict) -> str:
    """Formatea resultados como tabla ASCII."""
    rows = []
    for n in sorted(results.keys()):
        for method, metrics in sorted(results[n].items()):
            if metrics is None:
                rows.append([n, method, "ERROR", "ERROR", "ERROR", "ERROR"])
            else:
                rows.append([
                    n,
                    method,
                    int(metrics.get('reads', 0)),
                    int(metrics.get('writes', 0)),
                    int(metrics.get('total', 0)),
                    f"{metrics.get('elapsed_ms', 0):.2f}"
                ])
    
    headers = ["n", "método", "reads", "writes", "total_io", "tiempo_ms"]
    return tabulate(rows, headers=headers, tablefmt="grid")


# ============================================================================
# EXPERIMENTO 0: BufferManager con Caché Frío y Caliente
# ============================================================================

def experimento_0_buffer_comparison():
    """
    Comparativa CORREGIDA: 
    - Sin Buffer: invalida TODO (BufferManager + PageManager) antes de cada query.
    - Con Buffer (Frío): invalida solo BufferManager (PageManager mantiene mini-caché).
    - Con Buffer (Caliente): no invalida nada, caché completamente caliente.
    
    Mide tanto BÚSQUEDA como INSERCIÓN.
    """
    print("\n" + "="*70)
    print("EXPERIMENTO 0: Impacto del BufferManager (n=1,000)")
    print("="*70)
    
    n = 1000
    results = {}
    
    # ── Crear un solo engine para los 3 escenarios ──
    engine, pks, coords, io_load = setup_engine(
        csv_path=CSV_PATH,
        config=CONFIG,
        pk_col='id',
        spatial_meta={},
        n=n,
        table_name="exp0_buffer"
    )
    table_entry = engine._tables["exp0_buffer"]
    sample_pks = random.sample(pks, min(20, len(pks)))
    
    # ── [1/3] SIN BufferManager (disco frío total) ──
    print("\n[1/3] Evaluando SIN BufferManager (disco frío total)...")
    metrics_no_buf = {'reads': 0, 'writes': 0, 'elapsed_ms': 0.0, 'count': 0}
    for pk in sample_pks:
        # Invalidar TODO: BufferManager + PageManager subyacente
        table_entry.heap_pm.invalidate_cache()
        table_entry.index_pm.invalidate_cache()
        if hasattr(table_entry.heap_pm, 'pm'):
            table_entry.heap_pm.pm.invalidate_cache()
        if hasattr(table_entry.index_pm, 'pm'):
            table_entry.index_pm.pm.invalidate_cache()
        table_entry.io_counter.reset()
        
        result = engine.search("exp0_buffer", pk)
        if result:
            metrics_no_buf['reads'] += result.io_stats.get('reads', 0)
            metrics_no_buf['writes'] += result.io_stats.get('writes', 0)
            metrics_no_buf['elapsed_ms'] += result.elapsed_ms
            metrics_no_buf['count'] += 1
    
    if metrics_no_buf['count'] > 0:
        metrics_no_buf['reads'] = round(metrics_no_buf['reads'] / metrics_no_buf['count'])
        metrics_no_buf['writes'] = round(metrics_no_buf['writes'] / metrics_no_buf['count'])
        metrics_no_buf['elapsed_ms'] /= metrics_no_buf['count']
    metrics_no_buf['total'] = metrics_no_buf['reads'] + metrics_no_buf['writes']
    del metrics_no_buf['count']
    results['sin_buffer'] = metrics_no_buf
    
    # ── [2/3] CON BufferManager - FRÍO ──
    print("\n[2/3] Evaluando CON BufferManager (caché frío)...")
    metrics_buf_cold = {'reads': 0, 'writes': 0, 'elapsed_ms': 0.0, 'count': 0}
    for pk in sample_pks:
        # Invalidar SOLO BufferManager (PageManager conserva mini-caché de 1 pg)
        table_entry.heap_pm.invalidate_cache()
        table_entry.index_pm.invalidate_cache()
        # NO invalidamos table_entry.heap_pm.pm → simula "con buffer pero frío"
        table_entry.io_counter.reset()
        
        result = engine.search("exp0_buffer", pk)
        if result:
            metrics_buf_cold['reads'] += result.io_stats.get('reads', 0)
            metrics_buf_cold['writes'] += result.io_stats.get('writes', 0)
            metrics_buf_cold['elapsed_ms'] += result.elapsed_ms
            metrics_buf_cold['count'] += 1
    
    if metrics_buf_cold['count'] > 0:
        metrics_buf_cold['reads'] = round(metrics_buf_cold['reads'] / metrics_buf_cold['count'])
        metrics_buf_cold['writes'] = round(metrics_buf_cold['writes'] / metrics_buf_cold['count'])
        metrics_buf_cold['elapsed_ms'] /= metrics_buf_cold['count']
    metrics_buf_cold['total'] = metrics_buf_cold['reads'] + metrics_buf_cold['writes']
    del metrics_buf_cold['count']
    results['con_buffer_frío'] = metrics_buf_cold
    
    # ── [3/3] CON BufferManager - CALIENTE ──
    print("\n[3/3] Evaluando CON BufferManager (caché caliente)...")
    # Precalentar: buscar todos los samples una vez
    for pk in sample_pks:
        engine.search("exp0_buffer", pk)
    
    metrics_buf_warm = {'reads': 0, 'writes': 0, 'elapsed_ms': 0.0, 'count': 0}
    for pk in sample_pks:
        # NO invalidamos nada → todo en caché
        table_entry.io_counter.reset()
        
        result = engine.search("exp0_buffer", pk)
        if result:
            metrics_buf_warm['reads'] += result.io_stats.get('reads', 0)
            metrics_buf_warm['writes'] += result.io_stats.get('writes', 0)
            metrics_buf_warm['elapsed_ms'] += result.elapsed_ms
            metrics_buf_warm['count'] += 1
    
    if metrics_buf_warm['count'] > 0:
        metrics_buf_warm['reads'] = round(metrics_buf_warm['reads'] / metrics_buf_warm['count'])
        metrics_buf_warm['writes'] = round(metrics_buf_warm['writes'] / metrics_buf_warm['count'])
        metrics_buf_warm['elapsed_ms'] /= metrics_buf_warm['count']
    metrics_buf_warm['total'] = metrics_buf_warm['reads'] + metrics_buf_warm['writes']
    del metrics_buf_warm['count']
    results['con_buffer_caliente'] = metrics_buf_warm
    
    limpiar_archivos_tabla("exp0_buffer")
    
    # Mostrar tabla
    print("\n" + format_table_results({
        n: {
            "Sin Buffer": results['sin_buffer'],
            "Con Buffer (Frío)": results['con_buffer_frío'],
            "Con Buffer (Caliente)": results['con_buffer_caliente']
        }
    }))
    
    return results


# ============================================================================
# EXPERIMENTO 1: Sequential Index
# ============================================================================

def experimento_1_sequential_index():
    """Prueba Sequential Index con n=1k, 10k, 100k. Mide búsqueda exacta, rango e inserción."""
    print("\n" + "="*70)
    print("EXPERIMENTO 1: Sequential Index")
    print("="*70)
    
    results = {}
    ns = [1000, 10000, 100000]
    
    for n in ns:
        print(f"\n  n = {n:,} registros")
        
        engine, pks, coords, io_load = setup_engine(
            csv_path=CSV_PATH,
            config=CONFIG,
            pk_col='id',
            spatial_meta={},
            n=n,
            table_name="exp1_sequential"
        )
        
        results[n] = {}
        
        # ── Búsqueda exacta ──
        print(f"    [1/3] Búsqueda exacta...")
        sample_pks = random.sample(pks, min(20, len(pks)))
        metrics_exact = medir_busquedas(
            engine,
            "exp1_sequential",
            lambda pk: engine.search("exp1_sequential", pk),
            sample_pks,
            "búsqueda_exacta",
            n_samples=20
        )
        results[n]['búsqueda_exacta'] = metrics_exact
        
        # ── Búsqueda rango (REAL, no hardcoded) ──
        print(f"    [2/3] Búsqueda rango...")
        sorted_pks = sorted(pks)
        # Crear varios rangos de ~100 keys para promediar
        range_samples = []
        step = max(1, len(sorted_pks) // 5)
        for i in range(0, len(sorted_pks) - 1, step):
            end_idx = min(i + 100, len(sorted_pks) - 1)
            range_samples.append((sorted_pks[i], sorted_pks[end_idx]))
        range_samples = range_samples[:5]  # máximo 5 rangos
        
        metrics_range = medir_busquedas(
            engine,
            "exp1_sequential",
            lambda r: engine.range_search("exp1_sequential", r[0], r[1]),
            range_samples,
            "búsqueda_rango"
        )
        results[n]['búsqueda_rango'] = metrics_range
        
        # ── Inserción individual ──
        print(f"    [3/3] Inserción individual...")
        results[n]['inserción'] = _medir_insercion(engine, "exp1_sequential", pks)
        
        limpiar_archivos_tabla("exp1_sequential")
    
    print("\n" + format_table_results(results))
    return results


# ============================================================================
# EXPERIMENTO 2: Extendible Hashing
# ============================================================================

def _medir_insercion(engine, table_name, pks, n_inserts=10):
    """Helper: mide I/O promedio de inserción individual."""
    max_pk = max(pks)
    insert_metrics = {'reads': 0, 'writes': 0, 'elapsed_ms': 0.0, 'count': 0}
    for i in range(n_inserts):
        invalidar_cache_y_resetear(engine, table_name)
        new_pk = max_pk + 1000 + i
        try:
            data_tuple = (
                new_pk, f"TestCity{i}".encode().ljust(50, b'\x00'),
                9999, b"TC\x00", f"TestState{i}".encode().ljust(30, b'\x00'),
                9999, b"TX", f"TestCountry{i}".encode().ljust(30, b'\x00'),
                0.0, 0.0, f"Q{i}".encode().ljust(20, b'\x00')
            )
            record = Record(data_tuple)
            result = engine.insert(table_name, record)
            if result:
                insert_metrics['reads'] += result.io_stats.get('reads', 0)
                insert_metrics['writes'] += result.io_stats.get('writes', 0)
                insert_metrics['elapsed_ms'] += result.elapsed_ms
                insert_metrics['count'] += 1
        except Exception as e:
            print(f"    ⚠ Error inserción: {e}")
    
    if insert_metrics['count'] > 0:
        insert_metrics['reads'] = round(insert_metrics['reads'] / insert_metrics['count'])
        insert_metrics['writes'] = round(insert_metrics['writes'] / insert_metrics['count'])
        insert_metrics['elapsed_ms'] /= insert_metrics['count']
    insert_metrics['total'] = insert_metrics['reads'] + insert_metrics['writes']
    del insert_metrics['count']
    return insert_metrics


def experimento_2_extendible_hashing():
    """Prueba Extendible Hashing con n=1k, 10k, 100k. Mide búsqueda exacta e inserción."""
    print("\n" + "="*70)
    print("EXPERIMENTO 2: Extendible Hashing")
    print("="*70)
    
    results = {}
    ns = [1000, 10000, 100000]
    
    for n in ns:
        print(f"\n  n = {n:,} registros")
        
        engine, pks, coords, io_load = setup_engine(
            csv_path=CSV_PATH,
            config=CONFIG,
            pk_col='id',
            spatial_meta={},
            n=n,
            table_name="exp2_hashing",
            hash_meta=[{"nombre": "state_id"}]
        )
        
        results[n] = {}
        
        print(f"    [1/2] Búsqueda exacta...")
        # Extraer valores de state_id del CSV
        state_ids = []
        tmp_csv = DATA_DIR / f"_tmp_exp2_hashing_{n}.csv"
        crear_csv_temporal_n(CSV_PATH, n, tmp_csv)
        
        with open(tmp_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    state_ids.append(row['state_id'])
                except:
                    pass
        tmp_csv.unlink()
        
        state_ids = list(set(state_ids))[:min(20, len(set(state_ids)))]
        
        metrics_exact = medir_busquedas(
            engine,
            "exp2_hashing",
            lambda val: engine.search_hash("exp2_hashing", "state_id", val),
            state_ids,
            "búsqueda_exacta",
            n_samples=20
        )
        results[n]['búsqueda_exacta'] = metrics_exact
        
        # ── Inserción individual ──
        print(f"    [2/2] Inserción individual...")
        results[n]['inserción'] = _medir_insercion(engine, "exp2_hashing", pks)
        
        limpiar_archivos_tabla("exp2_hashing")
    
    print("\n" + format_table_results(results))
    return results


# ============================================================================
# EXPERIMENTO 3: B+ Tree
# ============================================================================

def experimento_3_btree():
    """Prueba B+ Tree con n=1k, 10k, 100k."""
    print("\n" + "="*70)
    print("EXPERIMENTO 3: B+ Tree")
    print("="*70)
    
    results = {}
    ns = [1000, 10000, 100000]
    
    for n in ns:
        print(f"\n  n = {n:,} registros")
        
        engine, pks, coords, io_load = setup_engine(
            csv_path=CSV_PATH,
            config=CONFIG,
            pk_col='id',
            spatial_meta={},
            n=n,
            table_name="exp3_btree",
            btree_meta=[{"nombre": "country_id"}]
        )
        
        results[n] = {}
        
        print(f"    [1/2] Búsqueda exacta...")
        # Extraer valores de country_id
        country_ids = []
        tmp_csv = DATA_DIR / f"_tmp_exp3_btree_{n}.csv"
        crear_csv_temporal_n(CSV_PATH, n, tmp_csv)
        
        with open(tmp_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    country_ids.append(int(row['country_id']))
                except:
                    pass
        tmp_csv.unlink()
        
        country_ids = list(set(country_ids))[:min(20, len(set(country_ids)))]
        
        metrics_exact = medir_busquedas(
            engine,
            "exp3_btree",
            lambda val: engine.search_btree("exp3_btree", "country_id", val),
            country_ids,
            "búsqueda_exacta",
            n_samples=20
        )
        results[n]['búsqueda_exacta'] = metrics_exact
        
        print(f"    [2/2] Búsqueda rango...")
        sorted_cids = sorted(country_ids)
        if len(sorted_cids) >= 2:
            range_samples_bt = []
            for ci in range(0, len(sorted_cids) - 1, max(1, len(sorted_cids) // 3)):
                range_samples_bt.append((sorted_cids[ci], sorted_cids[min(ci + 1, len(sorted_cids) - 1)]))
            range_samples_bt = range_samples_bt[:5]
            metrics_range = medir_busquedas(
                engine,
                "exp3_btree",
                lambda r: engine.range_search_btree("exp3_btree", "country_id", r[0], r[1]),
                range_samples_bt,
                "búsqueda_rango"
            )
            results[n]['búsqueda_rango'] = metrics_range
        else:
            results[n]['búsqueda_rango'] = {'reads': 0, 'writes': 0, 'total': 0, 'elapsed_ms': 0}
        
        # ── Inserción individual ──
        print(f"    [3/3] Inserción individual...")
        results[n]['inserción'] = _medir_insercion(engine, "exp3_btree", pks)
        
        limpiar_archivos_tabla("exp3_btree")
    
    print("\n" + format_table_results(results))
    return results


# ============================================================================
# EXPERIMENTO 4: R-Tree
# ============================================================================

def experimento_4_rtree():
    """Prueba R-Tree con n=1k, 10k, 100k."""
    print("\n" + "="*70)
    print("EXPERIMENTO 4: R-Tree")
    print("="*70)
    
    results = {}
    ns = [1000, 10000, 100000]
    
    for n in ns:
        print(f"\n  n = {n:,} registros")
        
        spatial_meta = {
            "col_x": "longitude",
            "col_y": "latitude"
        }
        
        engine, pks, coords, io_load = setup_engine(
            csv_path=CSV_PATH,
            config=CONFIG,
            pk_col='id',
            spatial_meta=spatial_meta,
            n=n,
            table_name="exp4_rtree"
        )
        
        results[n] = {}
        
        print(f"    [1/2] Búsqueda kNN (k=2)...")
        sample_coords = random.sample(coords, min(10, len(coords)))
        metrics_knn = medir_busquedas(
            engine,
            "exp4_rtree",
            lambda coord: engine.search_spatial_knn("exp4_rtree", coord[0], coord[1], k=2),
            sample_coords,
            "kNN_k2",
            n_samples=1
        )
        results[n]['kNN_k2'] = metrics_knn
        
        print(f"    [2/2] Búsqueda rango (radio=10)...")
        metrics_range = medir_busquedas(
            engine,
            "exp4_rtree",
            lambda coord: engine.search_spatial_radius("exp4_rtree", coord[0], coord[1], 10),
            sample_coords,
            "radio_10",
            n_samples=1
        )
        results[n]['radio_10'] = metrics_range
        
        # ── Inserción individual ──
        print(f"    [3/3] Inserción individual...")
        results[n]['inserción'] = _medir_insercion(engine, "exp4_rtree", pks, n_inserts=1)
        
        limpiar_archivos_tabla("exp4_rtree")
    
    print("\n" + format_table_results(results))
    return results


# ============================================================================
# GENERACIÓN DE GRÁFICAS - VERSIÓN MEJORADA CON MANEJO ROBUSTO
# ============================================================================

def plot_buffer_comparison(results):
    """✓ MEJORADO: Genera gráfica de BufferManager con manejo robusto de errores."""
    try:
        print("\n⏳ Generando gráfica de BufferManager...")
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        labels = ['Sin Buffer', 'Con Buffer\n(Caché Frío)', 'Con Buffer\n(Caché Caliente)']
        io_values = [
            results['sin_buffer']['total'],
            results['con_buffer_frío']['total'],
            results['con_buffer_caliente']['total']
        ]
        colors = [COLORS['without_buffer'], COLORS['with_buffer_cold'], COLORS['with_buffer_warm']]
        
        bars = ax.bar(labels, io_values, color=colors, edgecolor='black', linewidth=1.5, alpha=0.85)
        
        # Agregar valores en las barras
        for bar, val in zip(bars, io_values):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(val)}',
                    ha='center', va='bottom', fontsize=10, fontweight='bold')
        
        ax.set_ylabel('Total I/O (reads + writes)', fontsize=12, fontweight='bold')
        ax.set_title('Impacto del BufferManager — n=1,000 registros', 
                     fontsize=14, fontweight='bold')
        ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        
        # ✓ MEJORADO: Path absoluto y validación
        output_path = PLOTS_DIR / 'fig0_buffer.png'
        plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
        print(f"✓ Gráfica guardada: {output_path}")
        
        return str(output_path)
    
    except Exception as e:
        print(f"✗ ERROR al generar gráfica de BufferManager: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    finally:
        plt.close()


def plot_index_figure(results: Dict, index_name: str, methods: List[str]):
    """✓ MEJORADO: Genera figura con 2 subgráficas para un índice (log-log) con error handling."""
    try:
        print(f"\n⏳ Generando gráfica para {index_name}...")
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
        
        ns = sorted(results.keys())
        markers = ['o', 's', '^', 'D']
        
        # Validar que hay datos
        if not ns:
            print(f"⚠ No hay datos para graficar {index_name}")
            return None
        
        # Subgráfica 1: I/O vs n (log-log)
        for i, method in enumerate(methods):
            io_values = []
            for n in ns:
                if n in results and method in results[n]:
                    metrics = results[n][method]
                    if metrics:
                        io_values.append(max(metrics.get('total', 1), 1))  # Evitar log(0)
                    else:
                        io_values.append(1)
                else:
                    io_values.append(1)
            
            if any(v > 1 for v in io_values):  # Solo graficar si hay datos válidos
                ax1.loglog(ns, io_values, marker=markers[i % len(markers)], label=method,
                           linewidth=2, markersize=8)
        
        ax1.set_xlabel('Número de registros (n)', fontsize=11, fontweight='bold')
        ax1.set_ylabel('Total I/O (reads + writes)', fontsize=11, fontweight='bold')
        ax1.set_title('Accesos a Disco vs n', fontsize=12, fontweight='bold')
        ax1.legend(loc='best', fontsize=10)
        ax1.grid(True, alpha=0.3, which='both')
        
        # Subgráfica 2: Tiempo vs n (log-log)
        for i, method in enumerate(methods):
            time_values = []
            for n in ns:
                if n in results and method in results[n]:
                    metrics = results[n][method]
                    if metrics:
                        time_values.append(max(metrics.get('elapsed_ms', 0.1), 0.1))  # Evitar log(0)
                    else:
                        time_values.append(0.1)
                else:
                    time_values.append(0.1)
            
            if any(v > 0.1 for v in time_values):
                ax2.loglog(ns, time_values, marker=markers[i % len(markers)], label=method,
                           linewidth=2, markersize=8)
        
        ax2.set_xlabel('Número de registros (n)', fontsize=11, fontweight='bold')
        ax2.set_ylabel('Tiempo (ms)', fontsize=11, fontweight='bold')
        ax2.set_title('Tiempo de Ejecución vs n', fontsize=12, fontweight='bold')
        ax2.legend(loc='best', fontsize=10)
        ax2.grid(True, alpha=0.3, which='both')
        
        fig.suptitle(f'{index_name}', fontsize=14, fontweight='bold', y=0.99)
        plt.tight_layout()
        
        # ✓ MEJORADO: Path absoluto y validación
        safe_name = index_name.lower().replace(' ', '_').replace('+', 'plus')
        output_path = PLOTS_DIR / f'fig_{safe_name}.png'
        
        plt.savefig(str(output_path), dpi=300, bbox_inches='tight')
        print(f"✓ Gráfica guardada: {output_path}")
        
        return str(output_path)
    
    except Exception as e:
        print(f"✗ ERROR al generar gráfica para {index_name}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    finally:
        plt.close()


# ============================================================================
# MENÚ INTERACTIVO
# ============================================================================

def main_menu():
    """Menú principal interactivo."""
    all_results = {}
    generated_plots = []
    
    while True:
        print("\n" + "="*70)
        print("EVALUACIÓN EXPERIMENTAL - MINI SGBD")
        print("="*70)
        print("\n[0] Salir")
        print("[1] Exp 0: Impacto del BufferManager")
        print("[2] Exp 1: Sequential Index (1k, 10k, 100k)")
        print("[3] Exp 2: Extendible Hashing (1k, 10k, 100k)")
        print("[4] Exp 3: B+ Tree (1k, 10k, 100k)")
        print("[5] Exp 4: R-Tree (1k, 10k, 100k)")
        print("[6] Generar todas las gráficas y exportar")
        print("[7] Ejecutar TODOS los experimentos")
        print(f"\n📊 Gráficas generadas: {len(generated_plots)}")
        print(f"📁 Ubicación: {PLOTS_DIR}")
        
        choice = input("\nSelecciona opción: ").strip()
        
        try:
            if choice == '0':
                print("\n✓ Saliendo...")
                break
            
            elif choice == '1':
                print("\nEjecutando Experimento 0...")
                results = experimento_0_buffer_comparison()
                plot_path = plot_buffer_comparison(results)
                if plot_path:
                    generated_plots.append(plot_path)
                all_results['exp0'] = results
                print("✓ Experimento 0 completado")
            
            elif choice == '2':
                print("\nEjecutando Experimento 1...")
                results = experimento_1_sequential_index()
                plot_path = plot_index_figure(results, 'Sequential Index', 
                                ['búsqueda_exacta', 'búsqueda_rango', 'inserción'])
                if plot_path:
                    generated_plots.append(plot_path)
                all_results['exp1_sequential'] = results
                print("✓ Experimento 1 completado")
            
            elif choice == '3':
                print("\nEjecutando Experimento 2...")
                results = experimento_2_extendible_hashing()
                plot_path = plot_index_figure(results, 'Extendible Hashing', 
                                ['búsqueda_exacta', 'inserción'])
                if plot_path:
                    generated_plots.append(plot_path)
                all_results['exp2_hashing'] = results
                print("✓ Experimento 2 completado")
            
            elif choice == '4':
                print("\nEjecutando Experimento 3...")
                results = experimento_3_btree()
                plot_path = plot_index_figure(results, 'B+ Tree', 
                                ['búsqueda_exacta', 'búsqueda_rango', 'inserción'])
                if plot_path:
                    generated_plots.append(plot_path)
                all_results['exp3_btree'] = results
                print("✓ Experimento 3 completado")
            
            elif choice == '5':
                print("\nEjecutando Experimento 4...")
                print("⚠ Advertencia: Esto puede tardar MUCHO (especialmente con 100k)")
                print("⚠ Si R-Tree es lento, aplica las optimizaciones del documento ANALISIS_Y_SOLUCIONES.md")
                confirm = input("¿Continuar? (s/n): ").strip().lower()
                if confirm == 's':
                    results = experimento_4_rtree()
                    plot_path = plot_index_figure(results, 'R-Tree', 
                                        ['kNN_k2', 'radio_0.2', 'inserción'])
                    if plot_path:
                        generated_plots.append(plot_path)
                    all_results['exp4_rtree'] = results
                    print("✓ Experimento 4 completado")
            
            elif choice == '6':
                if all_results:
                    export_results_to_csv(all_results)
                    print("\n✓ Gráficas y datos exportados")
                    print(f"📁 Ubicación: {PLOTS_DIR}")
                    print(f"📊 Gráficas generadas: {len(generated_plots)}")
                    for plot in generated_plots:
                        print(f"   - {Path(plot).name}")
                else:
                    print("\n⚠ No hay resultados para exportar. Ejecuta al menos un experimento.")
            
            elif choice == '7':
                print("\n" + "="*70)
                print("EJECUTANDO TODOS LOS EXPERIMENTOS")
                print("="*70)
                print("⚠ Esto puede tardar 15-20 minutos. Ten paciencia...")
                print("⚠ Si tarda demasiado (>10 min), revisa ANALISIS_Y_SOLUCIONES.md para optimizaciones\n")
                
                try:
                    all_results['exp0'] = experimento_0_buffer_comparison()
                    plot_path = plot_buffer_comparison(all_results['exp0'])
                    if plot_path:
                        generated_plots.append(plot_path)
                except Exception as e:
                    print(f"✗ Error en Exp 0: {e}")
                
                try:
                    res1 = experimento_1_sequential_index()
                    plot_path = plot_index_figure(res1, 'Sequential Index', 
                                        ['búsqueda_exacta', 'búsqueda_rango', 'inserción'])
                    if plot_path:
                        generated_plots.append(plot_path)
                    all_results['exp1_sequential'] = res1
                except Exception as e:
                    print(f"✗ Error en Exp 1: {e}")
                
                try:
                    res2 = experimento_2_extendible_hashing()
                    plot_path = plot_index_figure(res2, 'Extendible Hashing', ['búsqueda_exacta', 'inserción'])
                    if plot_path:
                        generated_plots.append(plot_path)
                    all_results['exp2_hashing'] = res2
                except Exception as e:
                    print(f"✗ Error en Exp 2: {e}")
                
                try:
                    res3 = experimento_3_btree()
                    plot_path = plot_index_figure(res3, 'B+ Tree', 
                                        ['búsqueda_exacta', 'búsqueda_rango', 'inserción'])
                    if plot_path:
                        generated_plots.append(plot_path)
                    all_results['exp3_btree'] = res3
                except Exception as e:
                    print(f"✗ Error en Exp 3: {e}")
                
                try:
                    res4 = experimento_4_rtree()
                    plot_path = plot_index_figure(res4, 'R-Tree', ['kNN_k2', 'radio_0.2', 'inserción'])
                    if plot_path:
                        generated_plots.append(plot_path)
                    all_results['exp4_rtree'] = res4
                except Exception as e:
                    print(f"✗ Error en Exp 4: {e}")
                
                export_results_to_csv(all_results)
                
                print("\n" + "="*70)
                print("✓ TODOS LOS EXPERIMENTOS COMPLETADOS")
                print("="*70)
                print(f"\n📊 Gráficas guardadas en: {PLOTS_DIR}")
                print(f"📈 Total generadas: {len(generated_plots)}")
                for plot in generated_plots:
                    print(f"   ✓ {Path(plot).name}")
                print(f"📊 Datos en CSV: {RESULTS_DIR / 'experimental_results.csv'}")
            
            else:
                print("\n⚠ Opción no válida")
        
        except KeyboardInterrupt:
            print("\n\n✓ Interrumpido por usuario")
            break
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()


def export_results_to_csv(all_results: Dict):
    """Exporta todos los resultados a un archivo CSV."""
    try:
        csv_path = RESULTS_DIR / 'experimental_results.csv'
        rows = []
        
        for exp_name, exp_data in all_results.items():
            if exp_name == 'exp0':
                # Buffer comparison
                for method, metrics in exp_data.items():
                    if metrics:
                        rows.append({
                            'experimento': 'Exp 0 - Buffer',
                            'n': 1000,
                            'metodo': method,
                            'reads': int(metrics.get('reads', 0)),
                            'writes': int(metrics.get('writes', 0)),
                            'total_io': int(metrics.get('total', 0)),
                            'elapsed_ms': float(metrics.get('elapsed_ms', 0))
                        })
            else:
                # Otros experimentos
                exp_label = exp_name.replace('_', ' ').title()
                for n, methods in exp_data.items():
                    for method, metrics in methods.items():
                        if metrics:
                            rows.append({
                                'experimento': exp_label,
                                'n': n,
                                'metodo': method,
                                'reads': int(metrics.get('reads', 0)),
                                'writes': int(metrics.get('writes', 0)),
                                'total_io': int(metrics.get('total', 0)),
                                'elapsed_ms': float(metrics.get('elapsed_ms', 0))
                            })
        
        df = pd.DataFrame(rows)
        df.to_csv(str(csv_path), index=False)
        print(f"✓ Resultados exportados a: {csv_path}")
    except Exception as e:
        print(f"✗ Error al exportar a CSV: {e}")


if __name__ == '__main__':
    main_menu()