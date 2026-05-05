import { useState, useEffect, useRef, useCallback, type ChangeEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { executeQuery, fetchDatasets, restartBackend, uploadDataset } from './api/api'
import { Button } from './components/Button'
import { Card } from './components/Card'
import { DatasetsPanel } from './components/DatasetsPanel'
import { OutputPanel } from './components/OutputPanel'
import { QueryEditor } from './components/QueryEditor'
import { QueryTabs } from './components/QueryTabs'
import { MainLayout } from './components/MainLayout'

// Constants (can be re-enabled if min/max limiting is needed again)
const MIN_LEFT_WIDTH = 420
const MIN_RIGHT_WIDTH = 320
const MIN_TOP_HEIGHT = 200
const MIN_BOTTOM_HEIGHT = 200
const COLLAPSE_WIDTH = 50 // Mínimo antes de colapsar completamente
const SPLITTER_SIZE = 20

type QueryTab = {
  id: string
  title: string
  query: string
}

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
})

export default function App() {
  // Tabs & Query state
  const [tabs, setTabs] = useState<QueryTab[]>(() => [createTab(1)])
  const [activeId, setActiveId] = useState<string>(() => tabs[0]?.id ?? '')

  // Datasets & Output state
  const [datasets, setDatasets] = useState<string[]>([])
  const [output, setOutput] = useState<string>('')

  // Loading states
  const [isLoadingDatasets, setIsLoadingDatasets] = useState(false)
  const [isExecuting, setIsExecuting] = useState(false)
  const [isRestarting, setIsRestarting] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string>('')

  // Layout state
  const [leftWidth, setLeftWidth] = useState(720)
  const [topHeight, setTopHeight] = useState(280)
  const [isVerticalSnapping, setIsVerticalSnapping] = useState(false)
  const [isHorizontalSnapping, setIsHorizontalSnapping] = useState(false)

  // Refs for dragging
  const dragRef = useRef<DragState>({
    type: null,
    startX: 0,
    startY: 0,
    startSize: 0,
    containerSize: 0,
  })
  const prevLeftWidthRef = useRef(leftWidth)
  const prevTopHeightRef = useRef(topHeight)

  const gridRef = useRef<HTMLDivElement | null>(null)
  const sideRef = useRef<HTMLDivElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const activeTab = tabs.find((tab) => tab.id === activeId) ?? tabs[0]

  // Initialize dimensions
  useEffect(() => {
    if (gridRef.current) {
      const width = gridRef.current.getBoundingClientRect().width
      setLeftWidth(Math.round(width * 0.6))
    }
    if (sideRef.current) {
      const height = sideRef.current.getBoundingClientRect().height
      setTopHeight(Math.round(height * 0.35))
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

        // Snap brusco: si está entre COLLAPSE_WIDTH y MIN_LEFT_WIDTH, fuerza a uno u otro
        let nextLeft = Math.min(Math.max(rawValue, COLLAPSE_WIDTH), maxLeft)

        if (nextLeft > COLLAPSE_WIDTH && nextLeft < MIN_LEFT_WIDTH) {
          // Está en la zona "gris", determina hacia dónde forzar basado en velocidad
          nextLeft = rawValue > (COLLAPSE_WIDTH + MIN_LEFT_WIDTH) / 2 ? MIN_LEFT_WIDTH : COLLAPSE_WIDTH
        }

        setLeftWidth(nextLeft)
      }

      if (dragState.type === 'horizontal' && sideRef.current) {
        const maxTop = dragState.containerSize - MIN_BOTTOM_HEIGHT - SPLITTER_SIZE
        const rawValue = dragState.startSize + (event.clientY - dragState.startY)

        // Snap brusco: si está entre COLLAPSE_WIDTH y MIN_TOP_HEIGHT, fuerza a uno u otro
        let nextTop = Math.min(Math.max(rawValue, COLLAPSE_WIDTH), maxTop)

        if (nextTop > COLLAPSE_WIDTH && nextTop < MIN_TOP_HEIGHT) {
          // Está en la zona "gris", determina hacia dónde forzar basado en velocidad
          nextTop = rawValue > (COLLAPSE_WIDTH + MIN_TOP_HEIGHT) / 2 ? MIN_TOP_HEIGHT : COLLAPSE_WIDTH
        }

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

  const handleExecute = async () => {
    if (!activeTab) return
    setIsExecuting(true)
    setStatusMessage('')
    try {
      const result = await executeQuery(activeTab.query)
      setOutput(result)
    } catch (error) {
      setOutput('')
      setStatusMessage('Ocurrio un error al ejecutar la query.')
    } finally {
      setIsExecuting(false)
    }
  }

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const handleUploadChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setStatusMessage('')
    try {
      const message = await uploadDataset(file)
      setStatusMessage(message)
      await loadDatasets()
    } catch (error) {
      setStatusMessage('No se pudo subir el dataset.')
    } finally {
      event.target.value = ''
    }
  }

  const handleRestart = async () => {
    setIsRestarting(true)
    setStatusMessage('')
    try {
      const message = await restartBackend()
      setOutput(message)
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
        <QueryEditor value={activeTab?.query ?? ''} onChange={handleQueryChange} />
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
      isLoading={isLoadingDatasets}
      onUploadClick={handleUploadClick}
    />
  )

  // Right bottom panel - wrap in Card to apply collapsed styling
  const rightBottomPanel = (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <OutputPanel output={output} isRestarting={isRestarting} onRestart={handleRestart} />
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
