export function Card({ children, className = '' }) {
  return <article className={`card ${className}`.trim()}>{children}</article>
}

export function CardContent({ children, className = '' }) {
  return <div className={className}>{children}</div>
}
