import type { ReactNode } from 'react'

type ButtonVariant = 'primary' | 'secondary' | 'ghost'

type ButtonProps = {
  children: ReactNode
  variant?: ButtonVariant
  onClick?: () => void
  disabled?: boolean
}

export function Button({ children, variant = 'primary', onClick, disabled }: ButtonProps) {
  const variantClass = `btn-${variant}`

  return (
    <button
      className={`btn ${variantClass}`}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  )
}
