import { useEffect, useState } from 'react'
import { formatTimestamp } from '../utils/dashboardUtils'
import PiPlexLogo from './PiPlexLogo'
import { API_URL as API, WEBHOOK_URL, INGEST_URL } from '../config'

const HOST = window.location.hostname
const SERVICES = [
  { name: 'Ingestion API',       port: 8000, url: `http://${HOST}:8000/health` },
  { name: 'API Layer',           port: 8001, url: `http://${HOST}:8001/health` },
  { name: 'AI Engine',           port: 8002, url: `http://${HOST}:8002/health` },
  { name: 'Webhook Collector',   port: 8003, url: `http://${HOST}:8003/health` },
]

function useServiceHealth() {
  const [health, setHealth] = useState({})
  useEffect(() => {
    const check = () => {
      SERVICES.forEach(s => {
        fetch(s.url)
          .then(r => setHealth(h => ({ ...h, [s.name]: r.ok })))
          .catch(()  => setHealth(h => ({ ...h, [s.name]: false })))
      })
    }
    check()
    const id = setInterval(check, 10000)
    return () => clearInterval(id)
  }, [])
  return health
}

function useDashboardData() {
  const [data, setData] = useState({ pipelines: [], errors: [] })
  useEffect(() => {
    const fetch_ = () => {
      const token = localStorage.getItem('apd_token')
      return fetch(`${API}/dashboard`, {
        headers: token ? { 'x-session-token': token } : {},
      })
        .then(r => r.json())
        .then(setData)
        .catch(() => {})
    }
    fetch_()
    const id = setInterval(fetch_, 5000)
    return () => clearInterval(id)
  }, [])
  return data
}

export default function HomePage({ user, onOpenDashboard, onSignOut, theme, toggleTheme }) {
  const health = useServiceHealth()
  const data   = useDashboardData()

  const failed  = data.pipelines.filter(p => p.status === 'Failed').length
  const success = data.pipelines.filter(p => p.status === 'Success').length
  const total   = data.pipelines.length
  const recentErrors = [...data.errors]
    .filter(e => e.detectedAt)
    .sort((a, b) => b.detectedAt.localeCompare(a.detectedAt))
    .slice(0, 4)

  const allHealthy    = SERVICES.every(s => health[s.name] === true)
  const healthyCount  = SERVICES.filter(s => health[s.name] === true).length

  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const firstName = user?.name?.split(' ')[0] || user?.email?.split('@')[0] || 'there'

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-page)', color: 'var(--text)', paddingTop: '72px' }}>

      {/* ── Nav ── */}
      <header className="dashboard-header">
        <div className="header-inner">
          <div className="header-brand">
            <PiPlexLogo height={28} />
            <div className="header-subtitle" style={{ marginTop: 0, borderLeft: '1px solid var(--border)', paddingLeft: '0.75rem' }}>Home</div>
          </div>
          <div className="header-actions">
            <span style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--text-secondary)' }}>{user?.name || user?.email}</span>
            <button className="theme-toggle" onClick={toggleTheme} title="Toggle dark/light mode">
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            <button className="dashboard-button" onClick={onOpenDashboard}>Open Dashboard →</button>
            <button className="dashboard-button btn-ghost" onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      </header>

      <div style={{ maxWidth: 1160, margin: '0 auto', padding: '2rem 1.5rem 4rem', display: 'flex', flexDirection: 'column', gap: '2rem' }}>

        {/* ── Welcome ── */}
        <div>
          <h1 style={{ fontSize: '1.75rem', fontWeight: 800, letterSpacing: '-0.03em', marginBottom: '0.35rem' }}>
            {greeting}, {firstName}
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            Here's what's happening across your pipelines right now.
          </p>
        </div>

        {/* ── Pipeline health stats ── */}
        <div className="db-stats-grid">
          <div className="db-stat-card">
            <p className="db-stat-label">Total pipelines</p>
            <p className="db-stat-value">{total}</p>
            <p className="db-stat-sub">tracked in the system</p>
          </div>
          <div className="db-stat-card">
            <p className="db-stat-label">Failing</p>
            <p className="db-stat-value" style={{ color: failed > 0 ? 'var(--failed-text)' : 'var(--text)' }}>{failed}</p>
            <p className="db-stat-sub">{failed > 0 ? 'need attention' : 'all clear'}</p>
          </div>
          <div className="db-stat-card">
            <p className="db-stat-label">Healthy</p>
            <p className="db-stat-value" style={{ color: 'var(--success-text)' }}>{success}</p>
            <p className="db-stat-sub">running successfully</p>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>

          {/* ── Recent errors ── */}
          <div className="db-stat-card" style={{ gridColumn: '1' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Recent errors</h2>
              <button className="dashboard-button btn-ghost" style={{ padding: '0.3rem 0.75rem', fontSize: '0.8rem' }} onClick={onOpenDashboard}>
                See all
              </button>
            </div>
            {recentErrors.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>No errors with timestamps yet.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {recentErrors.map((e, i) => (
                  <div key={i} style={{ borderLeft: '3px solid var(--failed-border)', paddingLeft: '0.75rem' }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--failed-text)', marginBottom: '0.15rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {e.error}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {e.pipeline} · {formatTimestamp(e.detectedAt)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Pipeline list ── */}
          <div className="db-stat-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Pipeline status</h2>
            </div>
            {data.pipelines.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>No pipelines yet.</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                {data.pipelines.slice(0, 6).map(p => (
                  <div key={p.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
                    <span style={{ fontSize: '0.82rem', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{p.name}</span>
                    <span style={{
                      fontSize: '0.7rem', fontWeight: 600, padding: '0.15rem 0.5rem',
                      borderRadius: 'var(--radius-full)',
                      background: p.status === 'Failed' ? 'var(--failed-bg)' : 'var(--success-bg)',
                      color: p.status === 'Failed' ? 'var(--failed-text)' : 'var(--success-text)',
                      border: `1px solid ${p.status === 'Failed' ? 'var(--failed-border)' : 'var(--success-border)'}`,
                      flexShrink: 0,
                    }}>
                      {p.status}
                    </span>
                  </div>
                ))}
                {data.pipelines.length > 6 && (
                  <button className="dashboard-button btn-ghost" style={{ padding: '0.3rem 0.75rem', fontSize: '0.8rem', marginTop: '0.25rem' }} onClick={onOpenDashboard}>
                    +{data.pipelines.length - 6} more
                  </button>
                )}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>

          {/* ── Service health ── */}
          <div className="db-stat-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
              <h2 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Service health</h2>
              <span style={{
                fontSize: '0.72rem', fontWeight: 600, padding: '0.2rem 0.6rem',
                borderRadius: 'var(--radius-full)',
                background: allHealthy ? 'var(--success-bg)' : 'var(--failed-bg)',
                color: allHealthy ? 'var(--success-text)' : 'var(--failed-text)',
                border: `1px solid ${allHealthy ? 'var(--success-border)' : 'var(--failed-border)'}`,
              }}>
                {healthyCount}/{SERVICES.length} online
              </span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              {SERVICES.map(s => (
                <div key={s.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div>
                    <span style={{ fontSize: '0.82rem', fontWeight: 500 }}>{s.name}</span>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginLeft: '0.4rem' }}>:{s.port}</span>
                  </div>
                  <span style={{ fontSize: '0.72rem', fontWeight: 600,
                    color: health[s.name] === true ? 'var(--success-text)' : health[s.name] === false ? 'var(--failed-text)' : 'var(--text-muted)',
                  }}>
                    {health[s.name] === true ? '● Online' : health[s.name] === false ? '● Offline' : '○ Checking'}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Quick actions ── */}
          <div className="db-stat-card">
            <h2 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '1rem' }}>Quick actions</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
              <button className="dashboard-button" style={{ justifyContent: 'flex-start' }} onClick={onOpenDashboard}>
                Open Dashboard →
              </button>
              <div style={{ background: 'var(--bg-input)', borderRadius: 'var(--radius-md)', padding: '0.75rem', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Airflow webhook URL</div>
                <code style={{ fontSize: '0.78rem', color: 'var(--accent)', wordBreak: 'break-all' }}>
                  {WEBHOOK_URL}/airflow
                </code>
              </div>
              <div style={{ background: 'var(--bg-input)', borderRadius: 'var(--radius-md)', padding: '0.75rem', border: '1px solid var(--border)' }}>
                <div style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '0.4rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Generic webhook URL</div>
                <code style={{ fontSize: '0.78rem', color: 'var(--accent)', wordBreak: 'break-all' }}>
                  {WEBHOOK_URL}/generic
                </code>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
