import { useRef, useState, useEffect, useMemo, type UIEvent } from 'react'
import { useLineNumbers } from '../hooks/useLineNumbers'
import sqlPatternsRaw from '../sqlPatterns.json?raw'

type QueryEditorProps = {
  value: string
  onChange: (value: string) => void
  onSelectionChange?: (selection: string) => void
}

type SqlPattern = {
  name: string
  pattern: string
}

const sqlPatterns: SqlPattern[] = JSON.parse(sqlPatternsRaw)

const tokenColor = (name: string): string => {
  if (name === 'SPACE') return 'var(--ink)'
  if (name === 'STRING') return '#0d7a55'
  if (name === 'NUM') return '#7c3aed'
  if (name === 'OP') return '#b45309'
  if (name === 'ID') return '#1f2937'
  return '#0f6fa3'
}

const escapeHtml = (text: string): string =>
  text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')

const highlightSql = (text: string): string => {
  let pos = 0
  const htmlParts: string[] = []

  while (pos < text.length) {
    let matched = false

    for (const token of sqlPatterns) {
      const regex = new RegExp(`^(?:${token.pattern})`, 'i')
      const match = regex.exec(text.slice(pos))
      if (!match) continue

      const lexeme = match[0]
      if (token.name === 'SPACE') {
        htmlParts.push(escapeHtml(lexeme))
      } else {
        htmlParts.push(
          `<span style="color:${tokenColor(token.name)};font-weight:600;">${escapeHtml(lexeme)}</span>`,
        )
      }

      pos += lexeme.length
      matched = true
      break
    }

    if (!matched) {
      htmlParts.push(escapeHtml(text[pos]))
      pos += 1
    }
  }

  if (text.endsWith('\n')) {
    htmlParts.push('\n')
  }

  return htmlParts.join('')
}

export function QueryEditor({ value, onChange, onSelectionChange }: QueryEditorProps) {
  const gutterRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const highlightRef = useRef<HTMLDivElement | null>(null)
  const editorRef = useRef<HTMLDivElement | null>(null)
  const [textareaWidth, setTextareaWidth] = useState(300)

  const safeValue = value ?? ''
  const hasText = safeValue.length > 0

  // Medir la altura visual de cada línea lógica considerando wrapping
  const { linePositions, scrollTop, handleScroll, measuringDivRef } = useLineNumbers(safeValue, textareaWidth)

  const highlightedHtml = useMemo(() => highlightSql(safeValue), [safeValue])

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
    if (highlightRef.current) {
      highlightRef.current.scrollTop = event.currentTarget.scrollTop
      highlightRef.current.scrollLeft = event.currentTarget.scrollLeft
    }
  }

  const handleSelectionChange = () => {
    if (!onSelectionChange || !textareaRef.current) return

    const { selectionStart, selectionEnd, value: textValue } = textareaRef.current
    const selectedText = selectionStart !== selectionEnd ? textValue.slice(selectionStart, selectionEnd) : ''
    onSelectionChange(selectedText)
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

      <div style={{ position: 'relative', minHeight: 0, height: '100%' }}>
        <div
          ref={highlightRef}
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            padding: '14px',
            fontFamily: "'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace",
            fontSize: '14px',
            lineHeight: '1.6',
            whiteSpace: 'pre-wrap',
            wordWrap: 'break-word',
            overflow: 'hidden',
            color: 'var(--ink)',
            pointerEvents: 'none',
            zIndex: 1,
          }}
          dangerouslySetInnerHTML={{ __html: highlightedHtml }}
        />

        <textarea
          ref={textareaRef}
          className="query-input"
          placeholder="Escribe aqui tu consulta..."
          value={safeValue}
          onChange={(event) => onChange(event.target.value)}
          onScroll={handleTextareaScroll}
          onSelect={handleSelectionChange}
          onMouseUp={handleSelectionChange}
          onKeyUp={handleSelectionChange}
          spellCheck={false}
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 2,
            color: hasText ? 'transparent' : 'var(--ink)',
            caretColor: 'var(--ink)',
          }}
        />
      </div>
    </div>
  )
}
