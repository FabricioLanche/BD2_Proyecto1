import { Button } from './Button'
import { Card } from './Card'

type OutputPanelProps = {
  output: string
  isRestarting: boolean
  onRestart: () => void
}

export function OutputPanel({ output, isRestarting, onRestart }: OutputPanelProps) {
  return (
    <Card title="Output" subtitle="Results" className="panel-output">
      <div className="panel-stack">
        <pre className="output-box">{output || 'Todavia no hay resultados.'}</pre>
        <div className="panel-footer">
          <span className="panel-hint">Reinicia el entorno y limpia datasets.</span>
          <Button variant="ghost" onClick={onRestart} disabled={isRestarting}>
            {isRestarting ? 'Reiniciando...' : 'Reiniciar'}
          </Button>
        </div>
      </div>
    </Card>
  )
}
