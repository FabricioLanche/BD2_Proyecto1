from enum import Enum
import queue


def _normalize_value(value):
  if isinstance(value, bytes):
    return value.decode('utf-8', errors='ignore').rstrip('\x00')
  if isinstance(value, tuple):
    return [_normalize_value(item) for item in value]
  if isinstance(value, list):
    return [_normalize_value(item) for item in value]
  if isinstance(value, dict):
    return {key: _normalize_value(item) for key, item in value.items()}
  return value

class LogLevel(Enum):
  INFO = "INFO"
  ERROR = "ERROR"
  WARNING = "WARNING"
  DEBUG = "DEBUG"
  IMAGE = "IMAGE"
  RESULT = "RESULT"

class Logger:
  def log(self, level: LogLevel, msg: str):
    pass

  def result(self, columns: list, rows: list, description: str = ""):
    """Encola un resultado estructurado (tabla) con columnas y filas."""
    pass

  def image(self, path: str):
    """Encola una referencia a una imagen generada por el servidor (path local)."""
    pass

  def info(self, msg: str):
    self.log(LogLevel.INFO, msg)

  def error(self, msg: str):
    self.log(LogLevel.ERROR, msg)

  def warning(self, msg: str):
    self.log(LogLevel.WARNING, msg)

  def debug(self, msg: str):
    self.log(LogLevel.DEBUG, msg)

class ConsoleLogger(Logger):
  def log(self, level: LogLevel, msg: str):
    print(f"[{level.value}]: {msg}")

  def result(self, columns: list, rows: list):
    print(f"Columnas: {', '.join(columns)}")
    for row in rows:
      print(f"  {row}")

  def image(self, path: str):
    print(f"[IMAGE]: {path}")

class QueueLogger(Logger):
  def __init__(self, q=None):
    self.q = q or queue.Queue()

  def log(self, level: LogLevel, msg: str):
    self.q.put({
        "level": level.value,
        "message": msg
    })

  def result(self, columns: list, rows: list):
    normalized_columns = [_normalize_value(column) for column in columns]
    normalized_rows = []

    for row in rows:
      if isinstance(row, dict):
        normalized_rows.append([
          _normalize_value(row.get(column)) for column in normalized_columns
        ])
      elif isinstance(row, (list, tuple)):
        normalized_rows.append([_normalize_value(item) for item in row])
      else:
        normalized_rows.append([_normalize_value(row)])

    self.q.put({
        "level": "RESULT",
        "type": "table",
        "columns": normalized_columns,
        "rows": normalized_rows
    })
  
  def image(self, path: str):
    # Enviar un mensaje estructurado indicando imagen
    self.q.put({
        "level": "IMAGE",
        "type": "image",
        "path": path
    })