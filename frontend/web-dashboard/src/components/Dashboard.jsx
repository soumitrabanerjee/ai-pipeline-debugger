import { useEffect, useMemo, useState } from 'react'
import { filterDashboardItems } from './dashboardData'
import CreatePipelineForm from './CreatePipelineForm'
import { Search } from './icons/Search'

/* ── Inline SVG Icons ── */

function AlertCircle({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  )
}

function CheckCircle({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  )
}

function Lightbulb({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18h6" />
      <path d="M10 22h4" />
      <path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14" />
    </svg>
  )
}

function Plus({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

function XIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

export default function Dashboard() {
  const [query, setQuery] = useState('')
  const [data, setData] = useState({ pipelines: [], errors: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [selectedPipeline, setSelectedPipeline] = useState(null)
  const [pipelineErrors, setPipelineErrors] = useState([])
  const [detailLoading, setDetailLoading] = useState(false)
  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem('theme') === 'dark'
  })

  const fetchData = async (isInitial = false) => {
    if (isInitial) setLoading(true)
    try {
      const response = await fetch('http://localhost:8001/dashboard')
      if (!response.ok) throw new Error('Failed to fetch dashboard data')
      const result = await response.json()
      setData(result)
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
    const intervalId = setInterval(() => fetchData(false), 5000)
    return () => clearInterval(intervalId)
  }, [])

  const handlePipelineCreated = () => {
    setShowCreateForm(false)
    fetchData(false)
  }

  const handlePipelineClick = async (pipeline) => {
    setSelectedPipeline(pipeline)
    setDetailLoading(true)
    try {
      const response = await fetch(`http://localhost:8001/pipelines/${encodeURIComponent(pipeline.name)}/errors`)
      if (!response.ok) throw new Error('Failed to fetch pipeline errors')
      const errors = await response.json()
      setPipelineErrors(errors)
    } catch (err) {
      console.error(err)
      setPipelineErrors([])
    } finally {
      setDetailLoading(false)
    }
  }

  const handleCloseDetail = () => {
    setSelectedPipeline(null)
    setPipelineErrors([])
  }

  const toggleDarkMode = () => {
    setDarkMode((prev) => {
      const next = !prev
      document.body.setAttribute('data-theme', next ? 'dark' : '')
      localStorage.setItem('theme', next ? 'dark' : 'light')
      return next
    })
  }

  useEffect(() => {
    document.body.setAttribute('data-theme', darkMode ? 'dark' : '')
  }, [])

  const filteredItems = useMemo(
    () => filterDashboardItems(query, data.pipelines, data.errors),
    [query, data]
  )

  const failureCount = data.pipelines.filter((p) => p.status === 'Failed').length

  if (loading && !data.pipelines.length) {
    return (
      <div className="dashboard-page" style={{ paddingTop: '6rem' }}>
        <div className="empty-state">
          <div className="empty-icon">...</div>
          <p>Loading dashboard...</p>
        </div>
      </div>
    )
  }

  if (error && !data.pipelines.length) {
    return (
      <div className="dashboard-page" style={{ paddingTop: '6rem' }}>
        <div className="empty-state">
          <div className="empty-icon"><AlertCircle size={32} /></div>
          <p>Failed to connect to the API</p>
          <p className="muted">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <>
      {/* ── Detail Modal ── */}
      {selectedPipeline && (
        <div className="modal-overlay" onClick={handleCloseDetail}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <h2>{selectedPipeline.name}</h2>
                <p className="muted" style={{ marginTop: '0.25rem' }}>
                  Last run: {selectedPipeline.lastRun}
                  <span style={{ margin: '0 0.5rem' }}>&middot;</span>
                  <span className={selectedPipeline.status === 'Failed' ? 'status-chip failed' : 'status-chip success'}>
                    <span className="status-dot" />
                    {selectedPipeline.status}
                  </span>
                </p>
              </div>
              <button className="modal-close" onClick={handleCloseDetail} aria-label="Close">
                <XIcon size={14} />
              </button>
            </div>

            <p className="modal-section-title">Error History</p>

            {detailLoading ? (
              <div className="empty-state"><p>Loading errors...</p></div>
            ) : pipelineErrors.length === 0 ? (
              <div className="empty-state">
                <div className="empty-icon"><CheckCircle size={28} /></div>
                <p>No errors recorded for this pipeline.</p>
              </div>
            ) : (
              <div className="dashboard-list">
                {pipelineErrors.map((item, i) => (
                  <article key={i} className="card analysis-card">
                    <p className="error-label">
                      <AlertCircle size={14} />
                      {item.error}
                    </p>
                    <p className="error-detail">{item.rootCause}</p>
                    <div className="fix-block">
                      <Lightbulb size={14} className="fix-icon" />
                      <span>{item.fix}</span>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Sticky Header ── */}
      <header className="dashboard-header">
        <div className="header-inner">
          <div className="header-brand">
            <div className="header-logo">AI</div>
            <div>
              <div className="header-title">Pipeline Debugger</div>
              <div className="header-subtitle">AI-Powered Root Cause Analysis</div>
            </div>
          </div>
          <div className="header-actions">
            <div className="live-dot" title="Live — polling every 5s" />
            <button
              type="button"
              className="theme-toggle"
              aria-label="Toggle dark mode"
              onClick={toggleDarkMode}
              title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {darkMode ? '\u2600\uFE0F' : '\uD83C\uDF19'}
            </button>
          </div>
        </div>
      </header>

      {/* ── Main Content ── */}
      <main className="dashboard-page">

        {/* Search + Add */}
        <div className="search-row">
          <div className="search-wrapper">
            <span className="search-icon"><Search size={16} /></span>
            <input
              aria-label="Search pipelines or errors"
              className="dashboard-input"
              placeholder="Search pipelines, errors, fixes..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <button
            type="button"
            className={`dashboard-button ${showCreateForm ? 'btn-ghost' : ''}`}
            onClick={() => setShowCreateForm(!showCreateForm)}
          >
            {showCreateForm ? (
              <>
                <XIcon size={14} />
                Cancel
              </>
            ) : (
              <>
                <Plus size={14} />
                Connect Pipeline
              </>
)}
          </button>
        </div>

        {/* Create Form */}
        {showCreateForm && (
          <CreatePipelineForm onPipelineCreated={handlePipelineCreated} />
        )}

        {/* Stats */}
        <section className="stats-grid" aria-label="Dashboard summary">
          <article className="card stat-card">
            <p className="stat-label">Total Pipelines</p>
            <p className="stat-value">{data.pipelines.length}</p>
            <p className="stat-sub">Across all workspaces</p>
          </article>
          <article className="card stat-card">
            <p className="stat-label">Failures Today</p>
            <p className="stat-value">{failureCount}</p>
            <p className="stat-sub">{failureCount === 0 ? 'All systems healthy' : 'Requires attention'}</p>
          </article>
          <article className="card stat-card">
            <p className="stat-label">Avg. Resolution</p>
            <p className="stat-value">12 min</p>
            <p className="stat-sub">Mean time to repair</p>
          </article>
        </section>

        {/* Pipeline Status */}
        <section>
          <div className="section-header">
            <h2 className="section-title">Pipeline Status</h2>
            <span className="section-badge">{filteredItems.pipelines.length}</span>
          </div>
          <div className="dashboard-list" style={{ marginTop: '0.75rem' }}>
            {filteredItems.pipelines.map((pipeline) => (
              <article
                key={pipeline.name}
                className="card status-card"
                onClick={() => handlePipelineClick(pipeline)}
                title="Click to view error history"
              >
                <div className="pipeline-info">
                  <p className="pipeline-name">{pipeline.name}</p>
                  <p className="muted">Last run: {pipeline.lastRun}</p>
                </div>
                <span className={pipeline.status === 'Failed' ? 'status-chip failed' : 'status-chip success'}>
                  <span className="status-dot" />
                  {pipeline.status}
                </span>
              </article>
            ))}
            {filteredItems.pipelines.length === 0 && (
              <div className="empty-state">
                <div className="empty-icon"><Search size={28} /></div>
                <p>No pipelines matched your search.</p>
              </div>
            )}
          </div>
        </section>

        {/* AI Root Cause Analysis */}
        <section>
          <div className="section-header">
            <h2 className="section-title">AI Root Cause Analysis</h2>
            <span className="section-badge">{filteredItems.errors.length}</span>
          </div>
          <div className="dashboard-list" style={{ marginTop: '0.75rem' }}>
            {filteredItems.errors.map((item) => (
              <article key={`${item.pipeline}-${item.error}`} className="card analysis-card">
                <p className="pipeline-name">{item.pipeline}</p>
                <p className="error-label">
                  <AlertCircle size={14} />
                  {item.error}
                </p>
                <p className="error-detail">{item.rootCause}</p>
                <div className="fix-block">
                  <Lightbulb size={14} className="fix-icon" />
                  <span>{item.fix}</span>
                </div>
              </article>
            ))}
            {filteredItems.errors.length === 0 && (
              <div className="empty-state">
                <div className="empty-icon"><CheckCircle size={28} /></div>
                <p>No errors matched your search.</p>
              </div>
            )}
          </div>
        </section>
      </main>
    </>
  )
}
