import { Button } from './Button'
import { Card } from './Card'

type DatasetsPanelProps = {
  datasets: string[]
  isLoading: boolean
  onUploadClick: () => void
}

export function DatasetsPanel({ datasets, isLoading, onUploadClick }: DatasetsPanelProps) {
  return (
    <Card
      title="Datasets"
      subtitle="Catalog"
      className="panel-datasets"
      action={
        <span className="panel-chip">
          {isLoading ? 'Cargando...' : `${datasets.length} csv`}
        </span>
      }
    >
      <div className="panel-stack">
        <ul className="dataset-list">
          {datasets.length === 0 ? (
            <li className="dataset-empty">No hay datasets cargados.</li>
          ) : (
            datasets.map((item) => (
              <li key={item} className="dataset-item">
                {item}
              </li>
            ))
          )}
        </ul>
        <div className="panel-footer">
          <span className="panel-hint">Sube archivos .csv para trabajar.</span>
          <Button variant="secondary" onClick={onUploadClick}>
            Subir CSV
          </Button>
        </div>
      </div>
    </Card>
  )
}
