import { useRef, useState, useEffect, type UIEvent } from 'react'
import { useLineNumbers } from '../hooks/useLineNumbers'

type QueryEditorProps = {
  value: string
  onChange: (value: string) => void
}

export function QueryEditor({ value, onChange }: QueryEditorProps) {
  const gutterRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const editorRef = useRef<HTMLDivElement | null>(null)
  const [textareaWidth, setTextareaWidth] = useState(300)

  // Medir la altura visual de cada línea lógica considerando wrapping
  const { linePositions, scrollTop, handleScroll, measuringDivRef } = useLineNumbers(value, textareaWidth)

  // Actualizar ancho cuando monta o cambia tamaño
  useEffect(() => {
    const updateWidth = () => {
      if (textareaRef.current) {
        setTextareaWidth(textareaRef.current.offsetWidth)
      }
    }

    updateWidth()

    const resizeObserver = new ResizeObserver(updateWidth)
    if (editorRef.current) {
      resizeObserver.observe(editorRef.current)
    }

    return () => resizeObserver.disconnect()
  }, [])

  const handleTextareaScroll = (event: UIEvent<HTMLTextAreaElement>) => {
    handleScroll(event)
    if (gutterRef.current) {
      gutterRef.current.scrollTop = event.currentTarget.scrollTop
    }
  }

  return (
    <div className="query-editor" ref={editorRef}>
      {/* Hidden measuring div para detectar wrapping */}
      <div
        ref={measuringDivRef}
        style={{
          position: 'absolute',
          visibility: 'hidden',
          whiteSpace: 'pre-wrap',
          wordWrap: 'break-word',
          fontFamily: "'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace",
          fontSize: '14px',
          lineHeight: '1.6',
          width: `${textareaWidth - 42}px`,
        }}
      />

      {/* Gutter with line numbers positioned according to visual lines */}
      <div
        className="query-gutter"
        ref={gutterRef}
        aria-hidden="true"
      >
        {linePositions.map((line) => (
          <div
            key={line.number}
            className="query-line"
            style={{
              position: 'absolute',
              top: `${line.top - scrollTop}px`,
              left: '8px',
              right: '0',
            }}
          >
            {line.number}
          </div>
        ))}
      </div>

      <textarea
        ref={textareaRef}
        className="query-input"
        placeholder="Escribe aqui tu consulta..."
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        onScroll={handleTextareaScroll}
        spellCheck={false}
      />
    </div>
  )
}
