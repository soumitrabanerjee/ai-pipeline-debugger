import { useEffect, useMemo, useState } from 'react'
import { filterDashboardItems } from './dashboardData'
import CreatePipelineForm from './CreatePipelineForm'
import { formatTimestamp, sortErrors, TIMEZONE_OPTIONS } from '../utils/dashboardUtils'
export default function Dashboard({ onBack, user, onSignOut, theme, toggleTheme }) {
  const [query, setQuery]                       = useState('')
  const [data, setData]                         = useState({ pipelines: [], errors: [] })
  const [loading, setLoading]                   = useState(true)
  const [error, setError]                       = useState(null)
  const [showCreateForm, setShowCreateForm]     = useState(false)
  const [selectedPipeline, setSelectedPipeline] = useState(null)
  const [pipelineErrors, setPipelineErrors]     = useState([])
  const [detailLoading, setDetailLoading]       = useState(false)
  const [errorSort, setErrorSort]               = useState('timestamp') // 'timestamp' | 'pipeline'
  const [timezone, setTimezone]                 = useState('local')

  const fetchData = async (isInitial = false) => {
    if (isInitial) setLoading(true)
    const token = localStorage.getItem('apd_token')
    try {
      const res = await fetch('http://localhost:8001/dashboard', {
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
    const id = setInterval(() => fetchData(false), 5000)
    return () => clearInterval(id)
  }, [])

  const handlePipelineClick = async (pipeline) => {
    setSelectedPipeline(pipeline)
    setDetailLoading(true)
    const token = localStorage.getItem('apd_token')
    try {
      const res = await fetch(`http://localhost:8001/pipelines/${encodeURIComponent(pipeline.name)}/errors`, {
        headers: token ? { 'x-session-token': token } : {},
      })
      if (!res.ok) throw new Error()
      setPipelineErrors(await res.json())
    } catch {
      setPipelineErrors([])
    } finally {
      setDetailLoading(false)
    }
  }

  const closeModal = () => { setSelectedPipeline(null); setPipelineErrors([]) }

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
            <p className="db-modal-section-label">Error History</p>
            <div className="db-modal-body">
              {detailLoading ? (
                <div className="db-center-state"><div className="db-spinner" /></div>
              ) : pipelineErrors.length === 0 ? (
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
              )}
            </div>
          </div>
        </div>
      )}

      <header className="dashboard-header">
        <div className="header-inner">
          <div className="header-brand">
            <div className="header-subtitle" style={{ marginTop: 0 }}>Dashboard</div>
          </div>
          <div className="header-actions">
            <span className="db-live-dot" title="Live — polling every 5s" />
            <span className="db-live-label">Live</span>
            {user && <span className="db-user-pill">{user.name || user.email}</span>}
            <button className="theme-toggle" onClick={toggleTheme} title="Toggle dark/light mode">
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            {onBack && <button className="dashboard-button" onClick={onBack}>← Home</button>}
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

      </main>
    </div>
  )
}
