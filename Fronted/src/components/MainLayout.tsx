import { useEffect, useState, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from 'react'

const COLLAPSE_OVERLAY_ANIMATION_MS = 180

function useOverlayVisibility(isCollapsed: boolean) {
  const [overlayVisible, setOverlayVisible] = useState(isCollapsed)
  const [overlayExiting, setOverlayExiting] = useState(false)

  useEffect(() => {
    if (isCollapsed) {
      setOverlayVisible(true)
      setOverlayExiting(false)
      return undefined
    }

    if (!overlayVisible) return undefined

    setOverlayExiting(true)
    const timeoutId = window.setTimeout(() => {
      setOverlayVisible(false)
      setOverlayExiting(false)
    }, COLLAPSE_OVERLAY_ANIMATION_MS)

    return () => window.clearTimeout(timeoutId)
  }, [isCollapsed, overlayVisible])

  return { overlayVisible, overlayExiting }
}

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
  isRightPanelCollapsed: boolean
  isDatasetsCollapsed: boolean
  isOutputCollapsed: boolean
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
  isRightPanelCollapsed,
  isDatasetsCollapsed,
  isOutputCollapsed,
}: MainLayoutProps) {
  const leftOverlay = useOverlayVisibility(isQueryEditorCollapsed)
  const rightSideOverlay = useOverlayVisibility(isRightPanelCollapsed)
  const topOverlay = useOverlayVisibility(isDatasetsCollapsed)
  const bottomOverlay = useOverlayVisibility(isOutputCollapsed)

  return (
    <div className="app-shell">
      <header className="app-header">{header}</header>

      <main
        ref={gridRef}
        className="app-grid"
        style={{ gridTemplateColumns: `${leftWidth}px var(--splitter-size) minmax(0, 1fr)` }}
      >
        <div className={`left-panel-stage ${isQueryEditorCollapsed ? 'is-collapsed' : ''}`}>
          {leftPanel}
          {leftOverlay.overlayVisible && (
            <div className={`collapse-overlay ${leftOverlay.overlayExiting ? 'is-exiting' : ''}`} />
          )}
        </div>
        <div
          className="splitter splitter-vertical"
          role="separator"
          aria-orientation="vertical"
          onPointerDown={verticalSplitterOnDragStart}
        />
        <div className={`side-stage ${isRightPanelCollapsed ? 'is-collapsed' : ''}`}>
          <div
            ref={sideRef}
            className="app-side"
            style={{ gridTemplateRows: `${topHeight}px var(--splitter-size) minmax(0, 1fr)` }}
          >
            <div className={`top-panel-stage ${isDatasetsCollapsed ? 'is-collapsed' : ''}`}>
              {rightTopPanel}
              {topOverlay.overlayVisible && (
                <div className={`collapse-overlay ${topOverlay.overlayExiting ? 'is-exiting' : ''}`} />
              )}
            </div>
            <div
              className="splitter splitter-horizontal"
              role="separator"
              aria-orientation="horizontal"
              onPointerDown={horizontalSplitterOnDragStart}
            />
            <div className={`right-panel-stage ${isOutputCollapsed ? 'is-collapsed' : ''}`}>
              {rightBottomPanel}
              {bottomOverlay.overlayVisible && (
                <div className={`collapse-overlay ${bottomOverlay.overlayExiting ? 'is-exiting' : ''}`} />
              )}
            </div>
          </div>
          {rightSideOverlay.overlayVisible && (
            <div className={`collapse-overlay ${rightSideOverlay.overlayExiting ? 'is-exiting' : ''}`} />
          )}
        </div>
      </main>
    </div>
  )
}

