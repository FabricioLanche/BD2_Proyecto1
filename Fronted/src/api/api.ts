import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
})

type QueryResponse = {
  result?: string
}

type DatasetsResponse = {
  datasets?: string[]
}

export async function executeQuery(query: string): Promise<string> {
  const { data } = await api.post<QueryResponse>('/query', { query })
  return data.result ?? 'La query se ejecutó correctamente.'
}

export async function fetchDatasets(): Promise<string[]> {
  const { data } = await api.get<DatasetsResponse>('/dataset/list')
  return data.datasets ?? []
}

export async function uploadDataset(file: File): Promise<string> {
  const formData = new FormData()
  formData.append('file', file)

  const { data } = await api.post<{ message?: string }>('/dataset', formData)
  return data.message ?? 'Dataset cargado'
}

export async function restartBackend(): Promise<string> {
  const { data } = await api.post<{ message?: string }>('/restart')
  return data.message ?? 'Datos reiniciados'
}