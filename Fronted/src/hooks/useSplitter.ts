import { useRef, useEffect } from 'react'

type DragState = {
  type: 'vertical' | 'horizontal' | null
  startX: number
  startY: number
  startSize: number
  containerSize: number
}

export type SplitterLimits = {
  minLeft?: number
  maxLeft?: number
  minRight?: number
  minTop?: number
  minBottom?: number
}

export function useSplitter(
  onVerticalDrag: (nextWidth: number) => void,
  onHorizontalDrag: (nextHeight: number) => void,
  limits: SplitterLimits = {},
) {
  const dragRef = useRef<DragState>({
    type: null,
    startX: 0,
    startY: 0,
    startSize: 0,
    containerSize: 0,
  })

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragRef.current
      if (!dragState.type) return

      if (dragState.type === 'vertical') {
        const { minLeft = 0, minRight = 0 } = limits
        const maxLeft = dragState.containerSize - minRight - 20 // 20 is splitter size
        if (maxLeft <= minLeft) return

        const nextLeft = Math.min(
          Math.max(dragState.startSize + (event.clientX - dragState.startX), minLeft),
          maxLeft,
        )
        onVerticalDrag(nextLeft)
      }

      if (dragState.type === 'horizontal') {
        const { minTop = 0, minBottom = 0 } = limits
        const maxTop = dragState.containerSize - minBottom - 20 // 20 is splitter size
        if (maxTop <= minTop) return

        const nextTop = Math.min(
          Math.max(dragState.startSize + (event.clientY - dragState.startY), minTop),
          maxTop,
        )
        onHorizontalDrag(nextTop)
      }
    }

    const handlePointerUp = () => {
      if (!dragRef.current.type) return
      dragRef.current.type = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }

    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    window.addEventListener('pointercancel', handlePointerUp)

    return () => {
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
      window.removeEventListener('pointercancel', handlePointerUp)
    }
  }, [limits, onVerticalDrag, onHorizontalDrag])

  const startVerticalDrag = (containerSize: number, currentSize: number) => {
    return (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      dragRef.current = {
        type: 'vertical',
        startX: event.clientX,
        startY: event.clientY,
        startSize: currentSize,
        containerSize,
      }
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    }
  }

  const startHorizontalDrag = (containerSize: number, currentSize: number) => {
    return (event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault()
      dragRef.current = {
        type: 'horizontal',
        startX: event.clientX,
        startY: event.clientY,
        startSize: currentSize,
        containerSize,
      }
      document.body.style.cursor = 'row-resize'
      document.body.style.userSelect = 'none'
    }
  }

  return { startVerticalDrag, startHorizontalDrag }
}
