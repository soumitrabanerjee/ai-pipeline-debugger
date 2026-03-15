import { useEffect, useMemo, useState } from 'react'
import { filterDashboardItems } from './dashboardData'
import CreatePipelineForm from './CreatePipelineForm'
import { formatTimestamp, sortErrors, sortRuns, truncateRunId, TIMEZONE_OPTIONS } from '../utils/dashboardUtils'
import PiPlexLogo from './PiPlexLogo'
import { API_URL } from '../config'
export default function Dashboard({ onBack, user, onSignOut, theme, toggleTheme, onOpenAdmin }) {
  const [query, setQuery]                       = useState('')
  const [data, setData]                         = useState({ pipelines: [], errors: [] })
  const [loading, setLoading]                   = useState(true)
  const [error, setError]                       = useState(null)
  const [showCreateForm, setShowCreateForm]     = useState(false)
  const [selectedPipeline, setSelectedPipeline] = useState(null)
  const [pipelineErrors, setPipelineErrors]     = useState([])
  const [pipelineRuns, setPipelineRuns]         = useState([])
  const [activeTab, setActiveTab]               = useState('errors') // 'errors' | 'runs'
  const [detailLoading, setDetailLoading]       = useState(false)
  const [errorSort, setErrorSort]               = useState('timestamp') // 'timestamp' | 'pipeline'
  const [timezone, setTimezone]                 = useState('local')
  const [apiKeys, setApiKeys]                   = useState([])
  const [newKeyName, setNewKeyName]             = useState('')
  const [newKeyValue, setNewKeyValue]           = useState(null)  // shown once after creation
  const [keyLoading, setKeyLoading]             = useState(false)
  const [keyError, setKeyError]                 = useState(null)

  const fetchApiKeys = async () => {
    const token = localStorage.getItem('apd_token')
    try {
      const res = await fetch(`${API_URL}/api-keys`, { headers: { 'x-session-token': token } })
      if (res.ok) setApiKeys(await res.json())
    } catch { /* silent */ }
  }

  const handleCreateKey = async (e) => {
    e.preventDefault()
    if (!newKeyName.trim()) { setKeyError('Enter a name for the key.'); return }
    setKeyLoading(true); setKeyError(null)
    const token = localStorage.getItem('apd_token')
    try {
      const res = await fetch(`${API_URL}/api-keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-session-token': token },
        body: JSON.stringify({ name: newKeyName.trim() }),
      })
      const data = await res.json()
      if (!res.ok) { setKeyError(data.detail || 'Failed to create key.'); return }
      setNewKeyValue(data.key)
      setNewKeyName('')
      fetchApiKeys()
    } catch { setKeyError('Could not reach the server.') }
    finally { setKeyLoading(false) }
  }

  const handleRevokeKey = async (keyId) => {
    if (!window.confirm('Revoke this API key? Any pipelines using it will stop sending events.')) return
    const token = localStorage.getItem('apd_token')
    try {
      await fetch(`${API_URL}/api-keys/${keyId}`, { method: 'DELETE', headers: { 'x-session-token': token } })
      fetchApiKeys()
    } catch { /* silent */ }
  }

  const fetchData = async (isInitial = false) => {
    if (isInitial) setLoading(true)
    const token = localStorage.getItem('apd_token')
    try {
      const res = await fetch(`${API_URL}/dashboard`, {
        headers: token ? { 'x-session-token': token } : {},
      })
      if (!res.ok) throw new Error('Failed to fetch dashboard data')
      setData(await res.json())
      setError(null)
    } catch (err) {
      console.error(err)
      if (data.pipelines.length === 0) setError(err.message)
    } finally {
      if (isInitial) setLoading(false)
    }
  }

  useEffect(() => {
    fetchData(true)
    fetchApiKeys()
    const id = setInterval(() => fetchData(false), 5000)
    return () => clearInterval(id)
  }, [])

  const handlePipelineClick = async (pipeline) => {
    setSelectedPipeline(pipeline)
    setActiveTab('errors')
    setDetailLoading(true)
    const token = localStorage.getItem('apd_token')
    const headers = token ? { 'x-session-token': token } : {}
    try {
      const [errRes, runRes] = await Promise.all([
        fetch(`${API_URL}/pipelines/${encodeURIComponent(pipeline.name)}/errors`, { headers }),
        fetch(`${API_URL}/pipelines/${encodeURIComponent(pipeline.name)}/runs`,   { headers }),
      ])
      setPipelineErrors(errRes.ok ? await errRes.json() : [])
      setPipelineRuns(runRes.ok  ? await runRes.json()  : [])
    } catch {
      setPipelineErrors([])
      setPipelineRuns([])
    } finally {
      setDetailLoading(false)
    }
  }

  const closeModal = () => {
    setSelectedPipeline(null)
    setPipelineErrors([])
    setPipelineRuns([])
    setActiveTab('errors')
  }

  const filteredItems = useMemo(() => {
    const base = filterDashboardItems(query, data.pipelines, data.errors)
    return { ...base, errors: sortErrors(base.errors, errorSort) }
  }, [query, data, errorSort])

  const failureCount = data.pipelines.filter(p => p.status === 'Failed').length

  if (loading && !data.pipelines.length) {
    return (
      <div className="db-shell">
        <div className="db-center-state">
          <div className="db-spinner" />
          <p className="db-center-text">Loading dashboard...</p>
        </div>
      </div>
    )
  }

  if (error && !data.pipelines.length) {
    return (
      <div className="db-shell">
        <div className="db-center-state">
          <div className="db-center-icon">⚠️</div>
          <p className="db-center-text">Failed to connect to the API</p>
          <p className="db-center-sub">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="db-shell">

      {selectedPipeline && (
        <div className="db-modal-overlay" onClick={closeModal}>
          <div className="db-modal" onClick={e => e.stopPropagation()}>

            {/* ── Modal header ── */}
            <div className="db-modal-header">
              <div>
                <h2 className="db-modal-title">{selectedPipeline.name}</h2>
                <div className="db-modal-meta">
                  <span className="db-modal-meta-text">Last run: {formatTimestamp(selectedPipeline.lastRun, timezone) ?? selectedPipeline.lastRun}</span>
                  <span className={selectedPipeline.status === 'Failed' ? 'db-chip db-chip-failed' : 'db-chip db-chip-success'}>
                    <span className="db-chip-dot" />
                    {selectedPipeline.status}
                  </span>
                </div>
              </div>
              <button className="db-modal-close" onClick={closeModal}>✕</button>
            </div>

            {/* ── Tab bar ── */}
            <div className="db-tab-bar">
              <button
                className={activeTab === 'errors' ? 'db-tab-btn db-tab-btn-active' : 'db-tab-btn'}
                onClick={() => setActiveTab('errors')}
              >
                ⚠ Errors
                {pipelineErrors.length > 0 && (
                  <span className="db-tab-count">{pipelineErrors.length}</span>
                )}
              </button>
              <button
                className={activeTab === 'runs' ? 'db-tab-btn db-tab-btn-active' : 'db-tab-btn'}
                onClick={() => setActiveTab('runs')}
              >
                ▶ Run History
                {pipelineRuns.length > 0 && (
                  <span className="db-tab-count">{pipelineRuns.length}</span>
                )}
              </button>
            </div>

            {/* ── Tab content ── */}
            <div className="db-modal-body">
              {detailLoading ? (
                <div className="db-center-state"><div className="db-spinner" /></div>

              ) : activeTab === 'errors' ? (
                pipelineErrors.length === 0 ? (
                  <div className="db-center-state">
                    <div className="db-center-icon">✓</div>
                    <p className="db-center-text">No errors recorded for this pipeline.</p>
                  </div>
                ) : (
                  pipelineErrors.map((item, i) => (
                    <div key={i} className="db-error-card">
                      <div className="db-analysis-card-header">
                        <p className="db-error-type">⚠ {item.error}</p>
                        {item.detectedAt && (
                          <span className="db-timestamp" title={item.detectedAt}>
                            🕐 {formatTimestamp(item.detectedAt, timezone)}
                          </span>
                        )}
                      </div>
                      <p className="db-error-cause">{item.rootCause}</p>
                      <div className="db-fix-block">
                        <span className="db-fix-icon">💡</span>
                        <span>{item.fix}</span>
                      </div>
                    </div>
                  ))
                )

              ) : (
                /* ── Run History tab ── */
                sortRuns(pipelineRuns).length === 0 ? (
                  <div className="db-center-state">
                    <div className="db-center-icon">○</div>
                    <p className="db-center-text">No runs recorded for this pipeline.</p>
                  </div>
                ) : (
                  sortRuns(pipelineRuns).map((run, i) => (
                    <div key={run.runId ?? i} className="db-run-card">
                      <div className="db-run-row">
                        <span className="db-run-id" title={run.runId}>
                          {truncateRunId(run.runId)}
                        </span>
                        <div className="db-run-right">
                          {run.createdAt && (
                            <span className="db-timestamp" title={run.createdAt}>
                              🕐 {formatTimestamp(run.createdAt, timezone)}
                            </span>
                          )}
                          <span className={run.status === 'Failed' ? 'db-chip db-chip-failed' : 'db-chip db-chip-success'}>
                            <span className="db-chip-dot" />
                            {run.status}
                          </span>
                        </div>
                      </div>
                    </div>
                  ))
                )
              )}
            </div>

          </div>
        </div>
      )}

      <header className="dashboard-header">
        <div className="header-inner">
          <div className="header-brand">
            <PiPlexLogo height={28} />
            <div className="header-subtitle" style={{ marginTop: 0, borderLeft: '1px solid var(--border)', paddingLeft: '0.75rem' }}>Dashboard</div>
          </div>
          <div className="header-actions">
            <span className="db-live-dot" title="Live — polling every 5s" />
            <span className="db-live-label">Live</span>
            {user && <span className="db-user-pill">{user.name || user.email}</span>}
            <button className="theme-toggle" onClick={toggleTheme} title="Toggle dark/light mode">
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            {onBack && <button className="dashboard-button" onClick={onBack}>← Home</button>}
            {user?.is_admin && onOpenAdmin && (
              <button className="dashboard-button" onClick={onOpenAdmin}>Admin →</button>
            )}
            <button className="dashboard-button btn-ghost" onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      </header>

      <main className="db-main">

        <div className="db-toolbar">
          <div className="db-search-wrap">
            <span className="db-search-icon">🔍</span>
            <input
              className="db-search-input"
              placeholder="Search pipelines, errors, fixes..."
              value={query}
              onChange={e => setQuery(e.target.value)}
              aria-label="Search"
            />
          </div>
          <button
            className={showCreateForm ? 'lp-btn-ghost' : 'lp-btn-primary'}
            style={{ whiteSpace: 'nowrap' }}
            onClick={() => setShowCreateForm(v => !v)}
          >
            {showCreateForm ? '✕ Cancel' : '+ Connect Pipeline'}
          </button>
        </div>

        {showCreateForm && (
          <CreatePipelineForm onPipelineCreated={() => { setShowCreateForm(false); fetchData(false) }} />
        )}

        <div className="db-stats-grid">
          {[
            { label: 'Total Pipelines', value: data.pipelines.length, sub: 'Across all workspaces' },
            { label: 'Failures',        value: failureCount,           sub: failureCount === 0 ? 'All systems healthy' : 'Requires attention' },
            { label: 'Avg. Resolution', value: '12 min',               sub: 'Mean time to repair' },
          ].map(s => (
            <div key={s.label} className="db-stat-card">
              <p className="db-stat-label">{s.label}</p>
              <p className="db-stat-value">{s.value}</p>
              <p className="db-stat-sub">{s.sub}</p>
            </div>
          ))}
        </div>

        <section className="db-section">
          <div className="db-section-header">
            <h2 className="db-section-title">Pipeline Status</h2>
            <span className="db-count-badge">{filteredItems.pipelines.length}</span>
          </div>
          {filteredItems.pipelines.length === 0 ? (
            <div className="db-empty"><p>No pipelines matched your search.</p></div>
          ) : filteredItems.pipelines.map(pipeline => (
            <div key={pipeline.name} className="db-pipeline-card" onClick={() => handlePipelineClick(pipeline)}>
              <div>
                <p className="db-pipeline-name">{pipeline.name}</p>
                <p className="db-pipeline-meta">Last run: {formatTimestamp(pipeline.lastRun, timezone) ?? pipeline.lastRun}</p>
              </div>
              <span className={pipeline.status === 'Failed' ? 'db-chip db-chip-failed' : 'db-chip db-chip-success'}>
                <span className="db-chip-dot" />
                {pipeline.status}
              </span>
            </div>
          ))}
        </section>

        <section className="db-section">
          <div className="db-section-header">
            <h2 className="db-section-title">AI Root Cause Analysis</h2>
            <div className="db-section-header-right">
              <span className="db-count-badge">{filteredItems.errors.length}</span>
              <div className="db-sort-toggle">
                <button
                  className={errorSort === 'timestamp' ? 'db-sort-btn db-sort-btn-active' : 'db-sort-btn'}
                  onClick={() => setErrorSort('timestamp')}
                >🕐 Time</button>
                <button
                  className={errorSort === 'pipeline' ? 'db-sort-btn db-sort-btn-active' : 'db-sort-btn'}
                  onClick={() => setErrorSort('pipeline')}
                >A→Z Pipeline</button>
              </div>
              <select
                className="db-tz-select"
                value={timezone}
                onChange={e => setTimezone(e.target.value)}
                title="Display timezone"
              >
                {TIMEZONE_OPTIONS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>
          {filteredItems.errors.length === 0 ? (
            <div className="db-empty"><p>No errors matched your search.</p></div>
          ) : filteredItems.errors.map((item, i) => (
            <div key={i} className="db-analysis-card">
              <div className="db-analysis-card-header">
                <p className="db-analysis-pipeline">{item.pipeline}</p>
                {item.detectedAt && (
                  <span className="db-timestamp" title={item.detectedAt}>
                    🕐 {formatTimestamp(item.detectedAt, timezone)}
                  </span>
                )}
              </div>
              {i === 0 && <span className="db-latest-badge">Latest</span>}
              <p className="db-error-type">⚠ {item.error}</p>
              <p className="db-error-cause">{item.rootCause}</p>
              <div className="db-fix-block">
                <span className="db-fix-icon">💡</span>
                <span>{item.fix}</span>
              </div>
            </div>
          ))}
        </section>

        <section className="db-section">
          <div className="db-section-header">
            <h2 className="db-section-title">API Keys</h2>
            <span className="db-count-badge">{apiKeys.filter(k => k.is_active).length} active</span>
          </div>

          {/* New key revealed after creation */}
          {newKeyValue && (
            <div style={{ background: 'var(--accent-subtle)', border: '1px solid rgba(99,102,241,0.3)', borderRadius: '10px', padding: '1rem 1.25rem', marginBottom: '1rem' }}>
              <p style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.4rem' }}>
                🔑 New key created — copy it now, it won't be shown again.
              </p>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <code style={{ flex: 1, fontSize: '0.78rem', color: 'var(--accent)', wordBreak: 'break-all', background: 'var(--bg-input)', padding: '0.5rem 0.75rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                  {newKeyValue}
                </code>
                <button className="lp-btn-primary" style={{ fontSize: '0.78rem', padding: '0.4rem 0.9rem', whiteSpace: 'nowrap' }}
                  onClick={() => { navigator.clipboard.writeText(newKeyValue); setNewKeyValue(null) }}>
                  Copy &amp; Close
                </button>
              </div>
            </div>
          )}

          {/* Existing keys list */}
          {apiKeys.length === 0 ? (
            <div className="db-empty"><p>No API keys yet.</p></div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
              {apiKeys.map(k => (
                <div key={k.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '10px', padding: '0.75rem 1rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1, minWidth: 0 }}>
                    <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{k.name}</span>
                    <code style={{ fontSize: '0.75rem', color: 'var(--text-muted)', background: 'var(--bg-input)', padding: '0.15rem 0.5rem', borderRadius: '6px', whiteSpace: 'nowrap' }}>{k.key_prefix}...</code>
                    <span style={{ fontSize: '0.7rem', fontWeight: 600, padding: '0.15rem 0.5rem', borderRadius: 'var(--radius-full)', background: k.is_active ? 'var(--success-bg)' : 'var(--failed-bg)', color: k.is_active ? 'var(--success-text)' : 'var(--failed-text)', border: `1px solid ${k.is_active ? 'var(--success-border)' : 'var(--failed-border)'}`, whiteSpace: 'nowrap' }}>
                      {k.is_active ? 'Active' : 'Revoked'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexShrink: 0 }}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{k.created_at?.slice(0, 10)}</span>
                    {k.is_active && (
                      <button className="lp-btn-ghost" style={{ fontSize: '0.75rem', padding: '0.25rem 0.65rem', color: 'var(--failed-text)' }}
                        onClick={() => handleRevokeKey(k.id)}>
                        Revoke
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Generate new key form */}
          <form onSubmit={handleCreateKey} style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <input
              className="db-search-input"
              placeholder="Key name, e.g. airflow-prod"
              value={newKeyName}
              onChange={e => setNewKeyName(e.target.value)}
              style={{ flex: 1, minWidth: '180px', paddingLeft: '1rem' }}
            />
            <button className="lp-btn-primary" type="submit" disabled={keyLoading} style={{ whiteSpace: 'nowrap' }}>
              {keyLoading ? <span className="auth-spinner" /> : '+ Generate Key'}
            </button>
          </form>
          {keyError && <p style={{ color: 'var(--failed-text)', fontSize: '0.8rem', marginTop: '0.4rem' }}>{keyError}</p>}
        </section>

      </main>
    </div>
  )
}
