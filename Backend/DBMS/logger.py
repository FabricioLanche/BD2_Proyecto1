from enum import Enum
import queue

class LogLevel(Enum):
  INFO = "INFO"
  ERROR = "ERROR"
  WARNING = "WARNING"
  DEBUG = "DEBUG"
  RESULT = "RESULT"

class Logger:
  def log(self, level: LogLevel, msg: str):
    pass

  def result(self, columns: list, rows: list, description: str = ""):
    """Encola un resultado estructurado (tabla) con columnas y filas."""
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

class QueueLogger(Logger):
  def __init__(self, q=None):
    self.q = q or queue.Queue()

  def log(self, level: LogLevel, msg: str):
    self.q.put({
        "level": level.value,
        "message": msg
    })

  def result(self, columns: list, rows: list):
    self.q.put({
        "level": "RESULT",
        "type": "table",
        "columns": columns,
        "rows": rows
    })