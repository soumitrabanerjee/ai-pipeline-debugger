export function Button({ children, className = '', type = 'button', ...props }) {
  return (
    <button type={type} className={`dashboard-button ${className}`.trim()} {...props}>
      {children}
    </button>
  )
}
