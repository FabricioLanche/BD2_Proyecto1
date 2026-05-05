import type { PointerEvent as ReactPointerEvent } from 'react'

type SplitterProps = {
  type: 'vertical' | 'horizontal'
  onDragStart: (event: ReactPointerEvent<HTMLDivElement>) => void
}

export function Splitter({ type, onDragStart }: SplitterProps) {
  const isVertical = type === 'vertical'

  return (
    <div
      className={`splitter splitter-${type}`}
      role="separator"
      aria-orientation={isVertical ? 'vertical' : 'horizontal'}
      onPointerDown={onDragStart}
    />
  )
}
