import { Button } from './Button'
import { Card } from './Card'
import type { QueryResultTable } from '../api/api'

type OutputView = 'logs' | 'results'

type OutputPanelProps = {
  logs: string
  resultTable: QueryResultTable | null
  image?: string | null
  view: OutputView
  onViewChange: (view: OutputView) => void
  isRestarting: boolean
  onRestart: () => void
}

export function OutputPanel({ logs, resultTable, image, view, onViewChange, isRestarting, onRestart }: OutputPanelProps) {
  const hasLogs = logs.trim().length > 0
  const hasResultRows = Boolean(resultTable && resultTable.rows.length > 0)
  
  const title = view === 'logs' ? 'Logs' : 'Results'

  const renderTableCell = (row: unknown, column: string) => {
    if (Array.isArray(row)) {
      return ''
    }

    if (row && typeof row === 'object') {
      const value = (row as Record<string, unknown>)[column]
      return String(value ?? '')
    }

    return String(row ?? '')
  }

  const renderRowValues = (row: unknown) => {
    if (Array.isArray(row)) {
      return row.map((cell) => String(cell ?? ''))
    }

    if (row && typeof row === 'object' && resultTable) {
      return resultTable.columns.map((column) => renderTableCell(row, column))
    }

    return [String(row ?? '')]
  }

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
          // Results view: prefer table, but if backend sent an image, render it instead of tabla
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

            if (hasResultRows && resultTable) {
              return (
                <div className="output-table-wrap">
                  <table className="output-table">
                    <thead>
                      <tr>
                        {resultTable.columns.map((column) => (
                          <th key={column}>{column}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {resultTable.rows.map((row, rowIndex) => {
                        const rowValues = renderRowValues(row)

                        return (
                        <tr key={`${rowIndex}-${rowValues.join('|')}`}>
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
            }

            return <div className="output-empty-state">No hay respuestas para esta consulta.</div>
          })()
        )}
        <div className="panel-footer">
          <span className="panel-hint">{view === 'logs' ? 'Muestra la respuesta en streaming del backend.' : 'Muestra los resultados tabulares de la consulta.'}</span>
          <Button variant="ghost" onClick={onRestart} disabled={isRestarting}>
            {isRestarting ? 'Reiniciando...' : 'Reiniciar'}
          </Button>
        </div>
      </div>
    </Card>
  )
}
