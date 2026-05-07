import { useState, useEffect, useRef, useCallback, type ChangeEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { deleteDataset, executeQuery, fetchDatasets, restartBackend, uploadDataset, type QueryResultTable } from './api/api'
import { Button } from './components/Button'
import { Card } from './components/Card'
import { DatasetsPanel } from './components/DatasetsPanel'
import { OutputPanel } from './components/OutputPanel'
import { QueryEditor } from './components/QueryEditor'
import { QueryTabs } from './components/QueryTabs'
import { MainLayout } from './components/MainLayout'

// Constants
const MIN_RIGHT_WIDTH = 50
const MIN_BOTTOM_HEIGHT = 50
const COLLAPSE_WIDTH = 50 // Mínimo antes de colapsar completamente
const SPLITTER_SIZE = 12 // Debe coincidir con --splitter-size en index.css
const INITIAL_LEFT_WIDTH = 420
const INITIAL_TOP_HEIGHT = 280
const LEFT_COLLAPSE_PERCENT = 0.75
const RIGHT_COLLAPSE_PERCENT = 0.35
const TOP_COLLAPSE_PERCENT = 0.8
const BOTTOM_COLLAPSE_PERCENT = 0.5

type QueryTab = {
  id: string
  title: string
  query: string
  selection: string
}

type OutputView = 'logs' | 'results'

type DragState = {
  type: 'vertical' | 'horizontal' | null
  startX: number
  startY: number
  startSize: number
  containerSize: number
}

const createTab = (index: number): QueryTab => ({
  id: `tab-${index}-${Date.now()}`,
  title: `Query ${index}`,
  query: '',
  selection: '',
})

export default function App() {
  // Tabs & Query state
  const [tabs, setTabs] = useState<QueryTab[]>(() => [createTab(1)])
  const [activeId, setActiveId] = useState<string>(() => tabs[0]?.id ?? '')

  // Datasets & Output state
  const [datasets, setDatasets] = useState<string[]>([])
  const [logs, setLogs] = useState<string>('')
  const [resultTable, setResultTable] = useState<QueryResultTable | null>(null)
  const [image, setImage] = useState<string | null>(null)
  const [outputView, setOutputView] = useState<OutputView>('logs')

  // Loading states
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(false)
  const [datasetOperation, setDatasetOperation] = useState<'idle' | 'uploading' | 'deleting'>('idle')
  const [uploadProgress, setUploadProgress] = useState(0)
  const [isExecuting, setIsExecuting] = useState(false)
  const [isRestarting, setIsRestarting] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string>('')

  // Layout state
  const [leftWidth, setLeftWidth] = useState(720)
  const [topHeight, setTopHeight] = useState(280)
  const [sideHeight, setSideHeight] = useState(0)
  const [gridWidth, setGridWidth] = useState(0)

  // Detect collapse state with one independent threshold per panel.
  const leftCollapseThreshold = INITIAL_LEFT_WIDTH * LEFT_COLLAPSE_PERCENT
  const rightCollapseThreshold = Math.max(gridWidth - INITIAL_LEFT_WIDTH - SPLITTER_SIZE, 0) * RIGHT_COLLAPSE_PERCENT
  const topCollapseThreshold = INITIAL_TOP_HEIGHT * TOP_COLLAPSE_PERCENT
  const bottomCollapseThreshold = Math.max(sideHeight - INITIAL_TOP_HEIGHT - SPLITTER_SIZE, 0) * BOTTOM_COLLAPSE_PERCENT
  const isQueryEditorCollapsed = leftWidth < leftCollapseThreshold
  const rightWidth = Math.max(gridWidth - leftWidth - SPLITTER_SIZE, 0)
  const isRightPanelCollapsed = gridWidth > 0 && rightWidth < rightCollapseThreshold
  const isDatasetsCollapsed = topHeight < topCollapseThreshold
  const outputHeight = Math.max(sideHeight - topHeight - SPLITTER_SIZE, 0)
  const isOutputCollapsed = sideHeight > 0 && outputHeight < bottomCollapseThreshold

  // Refs for dragging
  const dragRef = useRef<DragState>({
    type: null,
    startX: 0,
    startY: 0,
    startSize: 0,
    containerSize: 0,
  })

  const gridRef = useRef<HTMLDivElement | null>(null)
  const sideRef = useRef<HTMLDivElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const activeTab = tabs.find((tab) => tab.id === activeId) ?? tabs[0]
  const isDatasetsBusy = isLoadingDatasets || datasetOperation !== 'idle'

  // Initialize dimensions
  useEffect(() => {
    if (gridRef.current) {
      const width = gridRef.current.getBoundingClientRect().width
      setGridWidth(width)
      setLeftWidth(Math.round(width * 0.6))
    }
    if (sideRef.current) {
      const height = sideRef.current.getBoundingClientRect().height
      setSideHeight(height)
      setTopHeight(Math.round(height * 0.35))
    }
  }, [])

  useEffect(() => {
    if (!gridRef.current && !sideRef.current) return undefined

    const updateContainerSizes = () => {
      if (gridRef.current) {
        setGridWidth(gridRef.current.getBoundingClientRect().width)
      }
      if (sideRef.current) {
        setSideHeight(sideRef.current.getBoundingClientRect().height)
      }
    }

    updateContainerSizes()

    const observers: ResizeObserver[] = []

    if (gridRef.current) {
      const gridObserver = new ResizeObserver(updateContainerSizes)
      gridObserver.observe(gridRef.current)
      observers.push(gridObserver)
    }

    if (sideRef.current) {
      const sideObserver = new ResizeObserver(updateContainerSizes)
      sideObserver.observe(sideRef.current)
      observers.push(sideObserver)
    }

    return () => {
      observers.forEach((observer) => observer.disconnect())
    }
  }, [])

  // Load datasets on mount
  useEffect(() => {
    void loadDatasets()
  }, [])

  // Pointer move handler
  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragRef.current
      if (!dragState.type) return

      if (dragState.type === 'vertical' && gridRef.current) {
        const maxLeft = dragState.containerSize - MIN_RIGHT_WIDTH - SPLITTER_SIZE
        const rawValue = dragState.startSize + (event.clientX - dragState.startX)
        const nextLeft = Math.min(Math.max(rawValue, COLLAPSE_WIDTH), maxLeft)

        setLeftWidth(nextLeft)
      }

      if (dragState.type === 'horizontal' && sideRef.current) {
        const maxTop = dragState.containerSize - MIN_BOTTOM_HEIGHT - SPLITTER_SIZE
        const rawValue = dragState.startSize + (event.clientY - dragState.startY)
        const nextTop = Math.min(Math.max(rawValue, COLLAPSE_WIDTH), maxTop)

        setTopHeight(nextTop)
      }
    }

    const handlePointerUp = () => {
      if (!dragRef.current.type) return
      dragRef.current.type = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [])

  const handleVerticalDragStart = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!gridRef.current) return
    event.preventDefault()
    const rect = gridRef.current.getBoundingClientRect()
    dragRef.current = {
      type: 'vertical',
      startX: event.clientX,
      startY: event.clientY,
      startSize: leftWidth,
      containerSize: rect.width,
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [leftWidth])

  const handleHorizontalDragStart = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!sideRef.current) return
    event.preventDefault()
    const rect = sideRef.current.getBoundingClientRect()
    dragRef.current = {
      type: 'horizontal',
      startX: event.clientX,
      startY: event.clientY,
      startSize: topHeight,
      containerSize: rect.height,
    }
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
  }, [topHeight])

  const loadDatasets = async () => {
    setIsLoadingDatasets(true)
    try {
      const list = await fetchDatasets()
      setDatasets(list)
    } catch (error) {
      setStatusMessage('No se pudo cargar la lista de datasets.')
    } finally {
      setIsLoadingDatasets(false)
    }
  }

  const handleAddTab = () => {
    setTabs((prev) => {
      const next = [...prev, createTab(prev.length + 1)]
      setActiveId(next[next.length - 1].id)
      return next
    })
  }

  const handleCloseTab = (id: string) => {
    setTabs((prev) => {
      if (prev.length === 1) {
        const replacement = createTab(1)
        setActiveId(replacement.id)
        return [replacement]
      }

      const index = prev.findIndex((tab) => tab.id === id)
      const next = prev.filter((tab) => tab.id !== id)
      if (id === activeId) {
        const nextIndex = index > 0 ? index - 1 : 0
        setActiveId(next[nextIndex].id)
      }
      return next
    })
  }

  const handleQueryChange = (value: string) => {
    setTabs((prev) =>
      prev.map((tab) => (tab.id === activeId ? { ...tab, query: value } : tab)),
    )
  }

  const handleSelectionChange = (selection: string) => {
    setTabs((prev) =>
      prev.map((tab) => (tab.id === activeId ? { ...tab, selection } : tab)),
    )
  }

  const handleExecute = async () => {
    if (!activeTab) return
    setIsExecuting(true)
    setStatusMessage('')
    setLogs('')
    setResultTable(null)
    setImage(null)
    try {
      const queryToExecute = activeTab.selection.trim() || activeTab.query

      const result = await executeQuery(queryToExecute, ({ logs: nextLogs, resultTable: nextResultTable, image: nextImage }) => {
        setLogs(nextLogs)
        setResultTable(nextResultTable)
        setImage(nextImage ?? null)
        // Si llega una imagen o tabla, cambiar a la vista Results automáticamente
        if (nextImage || nextResultTable) setOutputView('results')
      })

      setLogs(result.logs)
      setResultTable(result.resultTable)
      setImage(result.image ?? null)
    } catch (error) {
      setLogs('')
      setResultTable(null)
      setStatusMessage('Ocurrio un error al ejecutar la query.')
    } finally {
      setIsExecuting(false)
    }
  }

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const handleDeleteDataset = async (datasetName: string) => {
    setStatusMessage('')
    setDatasetOperation('deleting')
    try {
      const message = await deleteDataset(datasetName)
      setStatusMessage(message)
      await loadDatasets()
    } catch (error) {
      setStatusMessage('No se pudo eliminar el dataset.')
    } finally {
      setDatasetOperation('idle')
    }
  }

  const handleUploadChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setStatusMessage('')
    setDatasetOperation('uploading')
    setIsLoadingDatasets(true)
    setUploadProgress(0)

    try {
      const message = await uploadDataset(file, (progress) => {
        setUploadProgress(progress)
      })
      setStatusMessage(message)
      await loadDatasets()
    } catch (error) {
      setStatusMessage('No se pudo subir el dataset.')
    } finally {
      event.target.value = ''
      setIsLoadingDatasets(false)
      setUploadProgress(0)
      setDatasetOperation('idle')
    }
  }

  const handleRestart = async () => {
    setIsRestarting(true)
    setStatusMessage('')
    try {
      const message = await restartBackend()
      setStatusMessage(message)
      // Limpiar todos los remanentes de ejecuciones anteriores
      setLogs('')
      setResultTable(null)
      setImage(null)
      setOutputView('logs')
      await loadDatasets()
    } catch (error) {
      setStatusMessage('No se pudo reiniciar el backend.')
    } finally {
      setIsRestarting(false)
    }
  }

  // Header content
  const header = (
    <>
      <div>
        <p className="app-kicker">BASE DE DATOS 2</p>
        <h1 className="app-title">Mini DBMS / Frontend</h1>
      </div>
      <p className="app-status">{statusMessage || 'Listo para ejecutar.'}</p>
    </>
  )

  // Left panel content
  const leftPanel = (
    <Card title="SQL Query" subtitle="Query editor" className="panel-query">
      <div className="panel-stack">
        <QueryTabs
          tabs={tabs.map(({ id, title }) => ({ id, title }))}
          activeId={activeId}
          onSelect={setActiveId}
          onAdd={handleAddTab}
          onClose={handleCloseTab}
        />
        <QueryEditor value={activeTab?.query ?? ''} onChange={handleQueryChange} onSelectionChange={handleSelectionChange} />
        <div className="panel-footer">
          <p className="panel-hint">Tip: Usa multiples pestañas para organizar tus consultas.</p>
          <Button variant="primary" onClick={handleExecute} disabled={isExecuting}>
            {isExecuting ? 'Ejecutando...' : 'Ejecutar'}
          </Button>
        </div>
      </div>
    </Card>
  )

  // Right top panel
  const rightTopPanel = (
    <DatasetsPanel
      datasets={datasets}
      isLoading={isDatasetsBusy}
      operation={datasetOperation}
      uploadProgress={uploadProgress}
      onUploadClick={handleUploadClick}
      onDeleteDataset={handleDeleteDataset}
    />
  )

  // Right bottom panel - wrap in Card to apply collapsed styling
  const rightBottomPanel = (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, minWidth: 0 }}>
      <OutputPanel
        logs={logs}
        resultTable={resultTable}
        image={image}
        view={outputView}
        onViewChange={setOutputView}
        isRestarting={isRestarting}
        onRestart={handleRestart}
      />
    </div>
  )

  return (
    <>
      <MainLayout
        header={header}
        leftPanel={leftPanel}
        rightTopPanel={rightTopPanel}
        rightBottomPanel={rightBottomPanel}
        verticalSplitterOnDragStart={handleVerticalDragStart}
        horizontalSplitterOnDragStart={handleHorizontalDragStart}
        leftWidth={leftWidth}
        topHeight={topHeight}
        gridRef={gridRef}
        sideRef={sideRef}
        isQueryEditorCollapsed={isQueryEditorCollapsed}
        isRightPanelCollapsed={isRightPanelCollapsed}
        isDatasetsCollapsed={isDatasetsCollapsed}
        isOutputCollapsed={isOutputCollapsed}
      />

      <input
        ref={fileInputRef}
        type="file"
        accept=".csv"
        className="sr-only"
        onChange={handleUploadChange}
      />
    </>
  )
}
