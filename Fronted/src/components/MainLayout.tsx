import type { ReactNode, PointerEvent as ReactPointerEvent, RefObject } from 'react'

type MainLayoutProps = {
  header: ReactNode
  leftPanel: ReactNode
  rightTopPanel: ReactNode
  rightBottomPanel: ReactNode
  verticalSplitterOnDragStart: (event: ReactPointerEvent<HTMLDivElement>) => void
  horizontalSplitterOnDragStart: (event: ReactPointerEvent<HTMLDivElement>) => void
  leftWidth: number
  topHeight: number
  gridRef: RefObject<HTMLDivElement | null>
  sideRef: RefObject<HTMLDivElement | null>
  isQueryEditorCollapsed: boolean
}

export function MainLayout({
  header,
  leftPanel,
  rightTopPanel,
  rightBottomPanel,
  verticalSplitterOnDragStart,
  horizontalSplitterOnDragStart,
  leftWidth,
  topHeight,
  gridRef,
  sideRef,
  isQueryEditorCollapsed,
}: MainLayoutProps) {
  return (
    <div className="app-shell">
      <header className="app-header">{header}</header>

      <main
        ref={gridRef}
        className="app-grid"
        style={{ gridTemplateColumns: `${leftWidth}px var(--splitter-size) minmax(0, 1fr)` }}
      >
        <div style={{ position: 'relative', overflow: 'hidden' }}>
          {leftPanel}
          {isQueryEditorCollapsed && (
            <div className="collapse-overlay" />
          )}
        </div>
        <div
          className="splitter splitter-vertical"
          role="separator"
          aria-orientation="vertical"
          onPointerDown={verticalSplitterOnDragStart}
        />
        <div
          ref={sideRef}
          className="app-side"
          style={{ gridTemplateRows: `${topHeight}px var(--splitter-size) minmax(0, 1fr)` }}
        >
          {rightTopPanel}
          <div
            className="splitter splitter-horizontal"
            role="separator"
            aria-orientation="horizontal"
            onPointerDown={horizontalSplitterOnDragStart}
          />
          {rightBottomPanel}
        </div>
      </main>
    </div>
  )
}

