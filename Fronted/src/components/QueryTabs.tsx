type QueryTab = {
  id: string
  title: string
}

type QueryTabsProps = {
  tabs: QueryTab[]
  activeId: string
  onSelect: (id: string) => void
  onAdd: () => void
  onClose: (id: string) => void
}

export function QueryTabs({ tabs, activeId, onSelect, onAdd, onClose }: QueryTabsProps) {
  const showCloseButton = tabs.length > 1

  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLDivElement>, id: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(id)
    }
  }

  return (
    <div className="query-tabs">
      <div className="query-tabs-list">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={`query-tab ${tab.id === activeId ? 'is-active' : ''}`}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => handleTabKeyDown(event, tab.id)}
          >
            <span className="query-tab-label">{tab.title}</span>
            <button
              type="button"
              className={`query-tab-close ${showCloseButton ? '' : 'is-hidden'}`}
              disabled={!showCloseButton}
              aria-hidden={!showCloseButton}
              tabIndex={showCloseButton ? 0 : -1}
              onClick={(e) => {
                e.stopPropagation()
                onClose(tab.id)
              }}
              aria-label="Close tab"
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <button className="query-tab-add" onClick={onAdd} title="Add new query">
        +
      </button>
    </div>
  )
}
