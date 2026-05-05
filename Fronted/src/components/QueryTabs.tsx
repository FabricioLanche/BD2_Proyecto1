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
  return (
    <div className="query-tabs">
      <div className="query-tabs-list">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`query-tab ${tab.id === activeId ? 'is-active' : ''}`}
            onClick={() => onSelect(tab.id)}
          >
            <span className="query-tab-label">{tab.title}</span>
            <button
              className="query-tab-close"
              onClick={(e) => {
                e.stopPropagation()
                onClose(tab.id)
              }}
              aria-label="Close tab"
            >
              ×
            </button>
          </button>
        ))}
      </div>
      <button className="query-tab-add" onClick={onAdd} title="Add new query">
        +
      </button>
    </div>
  )
}
