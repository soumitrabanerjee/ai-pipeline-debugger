import { useEffect, useState } from 'react'
import PiPlexLogo from './PiPlexLogo'
import { API_URL } from '../config'

export default function AdminDashboard({ user, onSignOut, theme, toggleTheme, onBack }) {
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [pwInput, setPwInput]   = useState('')
  const [pwStatus, setPwStatus] = useState(null)   // null | 'saving' | 'ok' | 'error'

  useEffect(() => {
    const token = localStorage.getItem('apd_token')
    const headers = { 'x-session-token': token }
    Promise.all([
      fetch(`${API_URL}/admin/stats`, { headers }).then(r => r.json()),
      fetch(`${API_URL}/admin/users`, { headers }).then(r => r.json()),
    ]).then(([s, u]) => {
      setStats(s)
      setUsers(u)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="db-shell">
      <div className="db-center-state"><div className="db-spinner" /></div>
    </div>
  )

  return (
    <div className="db-shell">
      <header className="dashboard-header">
        <div className="header-inner">
          <div className="header-brand">
            <PiPlexLogo height={28} />
            <div className="header-subtitle" style={{ marginTop: 0, borderLeft: '1px solid var(--border)', paddingLeft: '0.75rem' }}>Admin</div>
          </div>
          <div className="header-actions">
            <button className="theme-toggle" onClick={toggleTheme}>{theme === 'dark' ? '☀️' : '🌙'}</button>
            {onBack && (
              <button className="dashboard-button btn-ghost" onClick={onBack}>← Back</button>
            )}
            <button className="dashboard-button btn-ghost" onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      </header>

      <main className="db-main">
        <h2 className="db-section-title" style={{ marginBottom: '1.5rem' }}>Platform Overview</h2>

        {stats && (
          <>
            <div className="db-stats-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: '1.5rem' }}>
              {[
                { label: 'Total Users',      value: stats.total_users,     sub: 'Registered accounts' },
                { label: 'Paid Users',       value: stats.paid_users,      sub: 'Active subscriptions' },
                { label: 'Free Users',       value: stats.free_users,      sub: 'Unpaid accounts' },
                { label: 'Total Pipelines',  value: stats.total_pipelines, sub: 'Across all workspaces' },
                { label: 'Claude API Calls', value: stats.total_errors,    sub: 'Errors analysed by AI' },
                { label: 'Total Runs',       value: stats.total_runs,      sub: 'Pipeline executions' },
              ].map(s => (
                <div key={s.label} className="db-stat-card">
                  <p className="db-stat-label">{s.label}</p>
                  <p className="db-stat-value">{s.value}</p>
                  <p className="db-stat-sub">{s.sub}</p>
                </div>
              ))}
            </div>

            <div className="db-stat-card" style={{ marginBottom: '1.5rem' }}>
              <p className="db-stat-label" style={{ marginBottom: '0.75rem' }}>Subscriptions by Plan</p>
              <div style={{ display: 'flex', gap: '1.5rem' }}>
                {['starter', 'pro', 'enterprise', null].map(plan => (
                  <div key={plan ?? 'free'}>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>{plan ?? 'Unpaid'}</p>
                    <p style={{ fontSize: '1.5rem', fontWeight: 700 }}>{stats.by_plan?.[plan] ?? 0}</p>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}

        {/* ── Set / change password ── */}
        <div className="db-stat-card" style={{ marginBottom: '1.5rem' }}>
          <p className="db-stat-label" style={{ marginBottom: '0.75rem' }}>Account Password</p>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
            Set or update the password for <strong>{user?.email}</strong> so you can log in with email + password.
          </p>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              type="password"
              placeholder="New password (min 8 chars)"
              value={pwInput}
              onChange={e => { setPwInput(e.target.value); setPwStatus(null) }}
              style={{
                background: 'var(--bg-input)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)', padding: '0.5rem 0.75rem',
                color: 'var(--text)', fontSize: '0.875rem', width: '260px',
              }}
            />
            <button
              className="dashboard-button"
              disabled={pwStatus === 'saving' || pwInput.length < 8}
              onClick={() => {
                setPwStatus('saving')
                const token = localStorage.getItem('apd_token')
                fetch(`${API_URL}/auth/set-password`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', 'x-session-token': token },
                  body: JSON.stringify({ password: pwInput }),
                })
                  .then(r => r.ok ? setPwStatus('ok') : setPwStatus('error'))
                  .catch(() => setPwStatus('error'))
              }}
            >
              {pwStatus === 'saving' ? 'Saving…' : 'Set Password'}
            </button>
            {pwStatus === 'ok'    && <span style={{ color: 'var(--success-text)', fontSize: '0.82rem' }}>Password updated!</span>}
            {pwStatus === 'error' && <span style={{ color: 'var(--failed-text)',  fontSize: '0.82rem' }}>Failed — try again.</span>}
          </div>
        </div>

        <section className="db-section">
          <div className="db-section-header">
            <h2 className="db-section-title">All Users</h2>
            <span className="db-count-badge">{users.length}</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', textAlign: 'left' }}>
                  {['Email', 'Name', 'Plan', 'API Key', 'Pipelines', 'Claude Calls', 'Runs', 'Joined'].map(h => (
                    <th key={h} style={{ padding: '0.5rem 0.75rem', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map((u, i) => (
                  <tr key={u.id ?? i} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '0.6rem 0.75rem' }}>
                      {u.email}
                      {u.is_admin && (
                        <span style={{ marginLeft: '0.4rem', fontSize: '0.65rem', background: 'var(--accent)', color: '#fff', borderRadius: '4px', padding: '0.1rem 0.35rem' }}>
                          admin
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', color: 'var(--text-secondary)' }}>{u.name || '—'}</td>
                    <td style={{ padding: '0.6rem 0.75rem' }}>
                      {u.plan
                        ? <span className="db-chip db-chip-success"><span className="db-chip-dot" />{u.plan}</span>
                        : <span style={{ color: 'var(--text-muted)' }}>free</span>
                      }
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', fontFamily: 'monospace', fontSize: '0.75rem', color: 'var(--accent)' }}>
                      {u.api_key_prefix || '—'}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>{u.pipeline_count}</td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>{u.error_count}</td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>{u.run_count}</td>
                    <td style={{ padding: '0.6rem 0.75rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      {u.created_at?.slice(0, 10) || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  )
}
