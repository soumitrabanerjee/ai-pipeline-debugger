export function Input({ className = '', ...props }) {
  return <input className={`dashboard-input ${className}`.trim()} {...props} />
}
