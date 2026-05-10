import axios, { type AxiosProgressEvent } from 'axios'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api').trim() || '/api'
const NORMALIZED_API_BASE_URL = API_BASE_URL.endsWith('/')
  ? API_BASE_URL.slice(0, -1)
  : API_BASE_URL

export const api = axios.create({
  baseURL: NORMALIZED_API_BASE_URL,
})

type DatasetsResponse = {
  datasets?: string[]
}

export type QueryResultTable = {
  columns: string[]
  rows: unknown[][]
}

export type QueryStreamSnapshot = {
  logs: string
  resultTable: QueryResultTable | null
  image?: string | null
}

export type ConcurrentQueryUser = {
  user_id: string
  query: string
}

function parseStreamLine(line: string): QueryStreamSnapshot {
  const trimmed = line.trim()

  if (!trimmed) {
    return { logs: '', resultTable: null }
  }

  try {
    const parsed = JSON.parse(trimmed) as {
      type?: string
      columns?: unknown
      rows?: unknown
      path?: string
      image?: string
      level?: string
    }

    if (parsed?.type === 'table' && Array.isArray(parsed.columns) && Array.isArray(parsed.rows)) {
      return {
        logs: '',
        resultTable: {
          columns: parsed.columns.map((column) => String(column)),
          rows: parsed.rows as unknown[][],
        },
      }
    }

    // Mensaje de imagen desde el backend
    if (parsed?.type === 'image' && (typeof parsed.path === 'string' || typeof parsed.image === 'string')) {
      return { logs: '', resultTable: null, image: (parsed.path ?? parsed.image) as string }
    }

    // Compatibilidad con logger que expone level: 'IMAGE' y path
    if (parsed?.level === 'IMAGE' && (typeof parsed.path === 'string' || typeof parsed.image === 'string')) {
      return { logs: '', resultTable: null, image: (parsed.path ?? parsed.image) as string }
    }
  } catch {
    // No es JSON estructurado; tratarlo como log plano.
  }

  return { logs: line, resultTable: null }
}

export async function executeQuery(
  query: string,
  onUpdate?: (snapshot: QueryStreamSnapshot) => void,
): Promise<QueryStreamSnapshot> {
  const response = await fetch(`${NORMALIZED_API_BASE_URL}/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ query }),
  })

  if (!response.ok) {
    const errorDetail = await response.text().catch(() => '')
    throw new Error(errorDetail || `Error HTTP ${response.status}`)
  }

  if (!response.body) {
    const fallbackText = await response.text()
    if (fallbackText) {
      const snapshot = fallbackText
        .split(/\r?\n/)
        .filter(Boolean)
        .reduce<QueryStreamSnapshot>((accumulator, line) => {
          const parsed = parseStreamLine(line)
          return {
            logs: parsed.logs ? [accumulator.logs, parsed.logs].filter(Boolean).join('\n') : accumulator.logs,
            resultTable: parsed.resultTable ?? accumulator.resultTable,
            image: (parsed as any).image ?? accumulator.image ?? null,
          }
        }, { logs: '', resultTable: null, image: null })

      onUpdate?.(snapshot)
      return snapshot
    }
    const emptySnapshot = { logs: '', resultTable: null, image: null }
    onUpdate?.(emptySnapshot)
    return emptySnapshot
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let bufferedText = ''
  let logs = ''
  let resultTable: QueryResultTable | null = null
  let image: string | null = null

  const emit = () => {
    onUpdate?.({ logs, resultTable, image })
  }

  const consumeLine = (line: string) => {
    const parsed = parseStreamLine(line)
    if (parsed.resultTable) {
      resultTable = parsed.resultTable
      emit()
      return
    }

    if ((parsed as any).image) {
      image = (parsed as any).image
      emit()
      return
    }

    if (parsed.logs) {
      logs = logs ? `${logs}\n${parsed.logs}` : parsed.logs
      emit()
    }
  }

  const flushBufferedText = (text: string) => {
    bufferedText += text

    const lines = bufferedText.split(/\r?\n/)
    bufferedText = lines.pop() ?? ''

    for (const line of lines) {
      consumeLine(line)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value, { stream: true })
    if (!chunk) continue

    flushBufferedText(chunk)
  }

  const trailing = decoder.decode()
  if (trailing) {
    flushBufferedText(trailing)
  }

  if (bufferedText.trim()) {
    consumeLine(bufferedText)
  }

  const finalSnapshot = { logs, resultTable, image }
  onUpdate?.(finalSnapshot)

  return finalSnapshot
}

function appendLogLine(currentLogs: string, line: string) {
  return currentLogs ? `${currentLogs}\n${line}` : line
}

export async function executeConcurrentQueries(
  users: ConcurrentQueryUser[],
  onUpdate?: (snapshot: QueryStreamSnapshot) => void,
): Promise<QueryStreamSnapshot> {
  const response = await fetch(`${NORMALIZED_API_BASE_URL}/query/concurrent`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ users }),
  })

  if (!response.ok) {
    const errorDetail = await response.text().catch(() => '')
    throw new Error(errorDetail || `Error HTTP ${response.status}`)
  }

  if (!response.body) {
    const fallbackText = await response.text()
    const snapshot = fallbackText
      .split(/\r?\n/)
      .filter(Boolean)
      .reduce<QueryStreamSnapshot>((accumulator, line) => {
        const parsed = parseStreamLine(line)
        return {
          logs: parsed.logs ? appendLogLine(accumulator.logs, parsed.logs) : accumulator.logs,
          resultTable: parsed.resultTable ?? accumulator.resultTable,
          image: (parsed as any).image ?? accumulator.image ?? null,
        }
      }, { logs: '', resultTable: null, image: null })

    onUpdate?.(snapshot)
    return snapshot
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let bufferedText = ''
  let logs = ''
  let resultTable: QueryResultTable | null = null
  let image: string | null = null

  const emit = () => {
    onUpdate?.({ logs, resultTable, image })
  }

  const consumeLine = (line: string) => {
    const trimmed = line.trim()
    if (!trimmed) return

    try {
      const parsed = JSON.parse(trimmed) as {
        type?: string
        user_id?: string
        query?: string
        elapsed_ms?: number
        columns?: unknown
        rows?: unknown
        path?: string
        image?: string
        level?: string
        message?: string
      }

      const userLabel = parsed.user_id ? `[${parsed.user_id}] ` : ''

      if (parsed.type === 'table' && Array.isArray(parsed.columns) && Array.isArray(parsed.rows)) {
        resultTable = {
          columns: parsed.columns.map((column) => String(column)),
          rows: parsed.rows as unknown[][],
        }
        emit()
        return
      }

      if (parsed.type === 'image' && (typeof parsed.path === 'string' || typeof parsed.image === 'string')) {
        image = (parsed.path ?? parsed.image) as string
        emit()
        return
      }

      if (parsed.type === 'start') {
        logs = appendLogLine(logs, `${userLabel}Inicia consulta concurrente${parsed.query ? `: ${parsed.query}` : ''}`)
        emit()
        return
      }

      if (parsed.type === 'done') {
        logs = appendLogLine(logs, `${userLabel}Finaliza consulta concurrente${typeof parsed.elapsed_ms === 'number' ? ` (${parsed.elapsed_ms.toFixed(3)} ms)` : ''}`)
        emit()
        return
      }

      if (parsed.level && parsed.message) {
        logs = appendLogLine(logs, `${userLabel}[${parsed.level}]: ${parsed.message}`)
        emit()
        return
      }
    } catch {
      // Si no es JSON válido, lo tratamos como log plano del stream.
    }

    logs = appendLogLine(logs, line)
    emit()
  }

  const flushBufferedText = (text: string) => {
    bufferedText += text

    const lines = bufferedText.split(/\r?\n/)
    bufferedText = lines.pop() ?? ''

    for (const line of lines) {
      consumeLine(line)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunk = decoder.decode(value, { stream: true })
    if (!chunk) continue

    flushBufferedText(chunk)
  }

  const trailing = decoder.decode()
  if (trailing) {
    flushBufferedText(trailing)
  }

  if (bufferedText.trim()) {
    consumeLine(bufferedText)
  }

  const finalSnapshot = { logs, resultTable, image }
  onUpdate?.(finalSnapshot)

  return finalSnapshot
}

export async function fetchDatasets(): Promise<string[]> {
  const { data } = await api.get<DatasetsResponse>('/dataset/list')
  return data.datasets ?? []
}

export async function uploadDataset(
  file: File,
  onProgress?: (progress: number) => void,
): Promise<string> {
  const formData = new FormData()
  formData.append('file', file)

  const { data } = await api.post<{ message?: string }>('/dataset', formData, {
    onUploadProgress: (event: AxiosProgressEvent) => {
      if (event.total && onProgress) {
        const progress = Math.round((event.loaded / event.total) * 100)
        onProgress(progress)
      }
    },
  })
  return data.message ?? 'Dataset cargado'
}

export async function deleteDataset(filename: string): Promise<string> {
  const { data } = await api.delete<{ message?: string }>(`/dataset/${encodeURIComponent(filename)}`)
  return data.message ?? 'Dataset eliminado'
}

export async function restartBackend(): Promise<string> {
  const { data } = await api.post<{ message?: string }>('/restart')
  return data.message ?? 'Datos reiniciados'
}