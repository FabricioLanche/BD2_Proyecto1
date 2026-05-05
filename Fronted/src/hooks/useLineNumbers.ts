import { useCallback, useState, useRef, useEffect } from 'react'

type LineInfo = {
  number: number
  top: number
}

type LineMetrics = {
  logicalLine: number
  visualHeight: number // en píxeles
  visualLines: number // cuántas líneas visuales ocupa
}

const FONT_SIZE = 14
const LINE_HEIGHT = 1.6
const LINE_HEIGHT_PX = FONT_SIZE * LINE_HEIGHT // 22.4px
const PADDING_TOP = 14

export function useLineNumbers(textareaValue: string, textareaWidth: number) {
  const [scrollTop, setScrollTop] = useState(0)
  const [lineMetrics, setLineMetrics] = useState<LineMetrics[]>([])
  const measuringDivRef = useRef<HTMLDivElement | null>(null)

  // Medir la altura visual de cada línea lógica considerando wrapping
  useEffect(() => {
    if (!measuringDivRef.current) return

    const lines = textareaValue.split('\n')
    const metrics: LineMetrics[] = []

    // Limpiar div de medición
    measuringDivRef.current.innerHTML = ''

    lines.forEach((line, index) => {
      const lineDiv = document.createElement('div')
      lineDiv.textContent = line || ' '
      lineDiv.style.whiteSpace = 'pre-wrap'
      lineDiv.style.wordWrap = 'break-word'
      lineDiv.style.fontFamily = "'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace"
      lineDiv.style.fontSize = `${FONT_SIZE}px`
      lineDiv.style.lineHeight = `${LINE_HEIGHT}`
      lineDiv.style.margin = '0'
      lineDiv.style.padding = '0'
      lineDiv.style.width = `${textareaWidth - 42}px` // Restar ancho del gutter (42px)

      if (measuringDivRef.current) {
        measuringDivRef.current.appendChild(lineDiv)
      }

      const visualHeight = lineDiv.offsetHeight
      const visualLines = Math.round(visualHeight / LINE_HEIGHT_PX)

      metrics.push({
        logicalLine: index,
        visualHeight,
        visualLines,
      })
    })

    setLineMetrics(metrics)
  }, [textareaValue, textareaWidth])

  // Calcular posiciones basado en líneas visuales
  const linePositions = useCallback((): LineInfo[] => {
    const positions: LineInfo[] = []
    let currentVisualTop = PADDING_TOP

    lineMetrics.forEach((metric) => {
      positions.push({
        number: metric.logicalLine + 1,
        top: currentVisualTop,
      })
      currentVisualTop += metric.visualHeight
    })

    return positions
  }, [lineMetrics])

  const handleScroll = useCallback((e: React.UIEvent<HTMLTextAreaElement>) => {
    setScrollTop(e.currentTarget.scrollTop)
  }, [])

  return {
    linePositions: linePositions(),
    scrollTop,
    handleScroll,
    measuringDivRef,
    lineMetrics,
  }
}
