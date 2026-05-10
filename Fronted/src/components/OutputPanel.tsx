import { Button } from './Button'
import { Card } from './Card'
import type { QueryConcurrencyTable, QueryResultTable } from '../api/api'

type OutputView = 'logs' | 'results'

type OutputPanelProps = {
  logs: string
  resultTable: QueryResultTable | null
  concurrencyTable?: QueryConcurrencyTable | null
  image?: string | null
  view: OutputView
  onViewChange: (view: OutputView) => void
  isRestarting: boolean
  onRestart: () => void
}

export function OutputPanel({ logs, resultTable, concurrencyTable, image, view, onViewChange, isRestarting, onRestart }: OutputPanelProps) {
  const hasLogs = logs.trim().length > 0
  
  const title = view === 'logs' ? 'Logs' : 'Results'

  const activeTable = concurrencyTable ?? resultTable
  const activeTableHasRows = Boolean(activeTable && activeTable.rows.length > 0)
  const isConcurrencyView = Boolean(concurrencyTable)

  const renderTable = (table: QueryResultTable | QueryConcurrencyTable) => (
    <div className="output-table-wrap">
      <table className="output-table">
        <thead>
          <tr>
            {table.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => {
            const rowValues = Array.isArray(row)
              ? row.map((cell) => String(cell ?? ''))
              : table.columns.map((column) => String((row as Record<string, unknown>)[column] ?? ''))

            // Si es tabla de concurrencia, colorear filas especiales
            const isConcurrency = Boolean(concurrencyTable)
            let rowClass = ''
            if (isConcurrency) {
              const actionIndex = table.columns.indexOf('action')
              const action = actionIndex >= 0 ? (rowValues[actionIndex] ?? '').toString().toLowerCase() : ''
              if (action === 'dead lock' || action === 'deadlock') {
                rowClass = 'concurrency-deadlock'
              } else if (action === 'wait') {
                rowClass = 'concurrency-wait'
              }
            }

            return (
              <tr key={`${rowIndex}-${rowValues.join('|')}`} className={rowClass}>
                {rowValues.map((cell, cellIndex) => (
                  <td key={`${rowIndex}-${cellIndex}`}>{String(cell ?? '')}</td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )

  return (
    <Card
      title={title}
      subtitle="Activity"
      className="panel-output"
      action={
        <div className="output-toggle" role="tablist" aria-label="Cambiar vista del panel de salida">
          <button
            type="button"
            className={`output-toggle-button ${view === 'logs' ? 'is-active' : ''}`}
            aria-pressed={view === 'logs'}
            onClick={() => onViewChange('logs')}
          >
            Logs
          </button>
          <button
            type="button"
            className={`output-toggle-button ${view === 'results' ? 'is-active' : ''}`}
            aria-pressed={view === 'results'}
            onClick={() => onViewChange('results')}
          >
            Results
          </button>
        </div>
      }
    >
      <div className="panel-stack">
        {view === 'logs' ? (
          <pre className="output-box">{hasLogs ? logs.trimEnd() : 'Todavia no hay logs del backend.'}</pre>
        ) : (
          (() => {
            if (image) {
              return (
                <div className="output-image-wrap">
                  <a href={image} target="_blank" rel="noreferrer" aria-label="Abrir imagen en nueva pestaña">
                    <img src={image} alt="R-Tree visualization" className="output-image" />
                  </a>
                </div>
              )
            }

            if (activeTableHasRows && activeTable) {
              return renderTable(activeTable)
            }

            return <div className="output-empty-state">No hay respuestas para esta consulta.</div>
          })()
        )}
        <div className="panel-footer">
          <span className="panel-hint">{view === 'logs' ? 'Muestra la respuesta en streaming del backend.' : isConcurrencyView ? 'Muestra la línea de tiempo de concurrencia y locks.' : 'Muestra los resultados tabulares de la consulta.'}</span>
          <Button variant="ghost" onClick={onRestart} disabled={isRestarting}>
            {isRestarting ? 'Reiniciando...' : 'Reiniciar'}
          </Button>
        </div>
      </div>
    </Card>
  )
}
