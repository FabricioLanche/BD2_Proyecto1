import type { ReactNode } from 'react'

type CardProps = {
  title: string
  subtitle?: string
  children: ReactNode
  action?: ReactNode
  className?: string
}

export function Card({ title, subtitle, children, action, className = '' }: CardProps) {
  return (
    <div className={`panel ${className}`}>
      <div className="panel-header">
        <div>
          <p className="panel-eyebrow">{subtitle}</p>
          <h2 className="panel-title">{title}</h2>
        </div>
        {action && <div className="panel-action">{action}</div>}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}

