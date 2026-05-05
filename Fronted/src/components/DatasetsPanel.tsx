import { Button } from './Button'
import { Card } from './Card'

type DatasetsPanelProps = {
  datasets: string[]
  isLoading: boolean
  operation: 'idle' | 'uploading' | 'deleting'
  uploadProgress: number
  onUploadClick: () => void
  onDeleteDataset: (datasetName: string) => void
}

export function DatasetsPanel({
  datasets,
  isLoading,
  operation,
  uploadProgress,
  onUploadClick,
  onDeleteDataset,
}: DatasetsPanelProps) {
  const showProgress = operation === 'uploading' && isLoading && uploadProgress > 0
  const isDeleting = operation === 'deleting'
  const isBusy = isLoading || operation !== 'idle'

  const handleCopyDataset = async (datasetName: string) => {
    try {
      await navigator.clipboard.writeText(datasetName)
    } catch {
      const fallbackInput = document.createElement('textarea')
      fallbackInput.value = datasetName
      fallbackInput.setAttribute('readonly', 'true')
      fallbackInput.style.position = 'absolute'
      fallbackInput.style.left = '-9999px'
      document.body.appendChild(fallbackInput)
      fallbackInput.select()
      document.execCommand('copy')
      document.body.removeChild(fallbackInput)
    }
  }

  const handleDatasetKeyDown = (event: React.KeyboardEvent<HTMLLIElement>, datasetName: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      void handleCopyDataset(datasetName)
    }
  }

  const handleDeleteClick = (event: React.MouseEvent<HTMLButtonElement>, datasetName: string) => {
    event.stopPropagation()
    onDeleteDataset(datasetName)
  }

  return (
    <Card
      title="Datasets"
      subtitle="Catalog"
      className="panel-datasets"
      action={
        <span className="panel-chip">
          {isDeleting ? 'Eliminando...' : isLoading ? (showProgress ? `${uploadProgress}%` : 'Procesando...') : `${datasets.length} csv`}
        </span>
      }
    >
      <div className="panel-stack">
        {isDeleting ? (
          <div className="dataset-loading-state" aria-live="polite">
            <div className="dataset-loading-copy">Eliminando dataset</div>
            <div className="upload-progress-container is-indeterminate">
              <div className="upload-progress-bar">
                <div className="upload-progress-fill is-indeterminate" />
              </div>
            </div>
          </div>
        ) : showProgress ? (
          <div className="dataset-loading-state" aria-live="polite">
            <div className="dataset-loading-copy">Procesando CSV</div>
            <div className="upload-progress-container">
              <div className="upload-progress-bar">
                <div className="upload-progress-fill" style={{ width: `${uploadProgress}%` }} />
              </div>
            </div>
          </div>
        ) : datasets.length === 0 ? (
          <div className="dataset-empty">No hay datasets cargados.</div>
        ) : (
          <div className="dataset-tree">
            <div className="dataset-tree-label">datasets/</div>
            <ul className="dataset-list">
              {datasets.map((item, index) => (
                <li
                  key={item}
                  className={`dataset-item ${index === datasets.length - 1 ? 'is-last' : ''}`}
                  role="button"
                  tabIndex={0}
                  title="Copiar nombre del dataset"
                  onClick={() => void handleCopyDataset(item)}
                  onKeyDown={(event) => handleDatasetKeyDown(event, item)}
                >
                  <span className="dataset-name">{item}</span>
                  <button
                    type="button"
                    className="dataset-delete-button"
                    title="Eliminar dataset"
                    aria-label={`Eliminar ${item}`}
                    disabled={isBusy}
                    onClick={(event) => handleDeleteClick(event, item)}
                  >
                    x
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="panel-footer">
          <span className="panel-hint">Sube archivos .csv para trabajar.</span>
          <Button variant="secondary" onClick={onUploadClick} disabled={isBusy}>
            {isBusy ? 'Procesando...' : 'Subir CSV'}
          </Button>
        </div>
      </div>
    </Card>
  )
}
