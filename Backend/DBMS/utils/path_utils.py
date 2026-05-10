from pathlib import Path

DBMS_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = DBMS_DIR / "data"
DATASETS_DIR = DBMS_DIR / "datasets"
GRAPH_DIR = DBMS_DIR / "graphs"

def _normalize_path(raw_path: str) -> Path:
    return Path(str(raw_path).strip().strip('"').strip("'"))


def _resolve_path(raw_path: str, base_dir: Path, must_exist: bool, create_parent: bool) -> str:
    path = _normalize_path(raw_path)

    if path.is_absolute():
        resolved = path
    else:
        resolved = base_dir / path.name

    if create_parent:
        resolved.parent.mkdir(parents=True, exist_ok=True)

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"No se encontró el archivo '{raw_path}' en '{resolved}'.")

    return str(resolved)


def resolve_dataset_path(raw_path: str) -> str:
    return _resolve_path(raw_path, DATASETS_DIR, must_exist=True, create_parent=False)


def resolve_data_path(raw_path: str, create_parent: bool = False) -> str:
    return _resolve_path(raw_path, DATA_DIR, must_exist=False, create_parent=create_parent)


def resolve_graph_path(raw_path: str, create_parent: bool = True) -> str:
    return _resolve_path(raw_path, GRAPH_DIR, must_exist=False, create_parent=create_parent)
