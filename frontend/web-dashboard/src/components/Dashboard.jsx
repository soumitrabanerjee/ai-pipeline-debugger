import { useEffect, useMemo, useState } from 'react'
import { filterDashboardItems } from './dashboardData'
import CreatePipelineForm from './CreatePipelineForm'

export default function Dashboard({ onBack }) {
  const [query, setQuery]                       = useState('')
  const [data, setData]                         = useState({ pipelines: [], errors: [] })
  const [loading, setLoading]                   = useState(true)
  const [error, setError]                       = useState(null)
  const [showCreateForm, setShowCreateForm]     = useState(false)
  const [selectedPipeline, setSelectedPipeline] = useState(null)
  const [pipelineErrors, setPipelineErrors]     = useState([])
  const [detailLoading, setDetailLoading]       = useState(false)

  const fetchData = async (isInitial = false) => {
    if (isInitial) setLoading(true)
    try {
      const res = await fetch('http://localhost:8001/dashboard')
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
    try {
      const res = await fetch(`http://localhost:8001/pipelines/${encodeURIComponent(pipeline.name)}/errors`)
      if (!res.ok) throw new Error()
      setPipelineErrors(await res.json())
    } catch {
      setPipelineErrors([])
    } finally {
      setDetailLoading(false)
    }
  }

  const closeModal = () => { setSelectedPipeline(null); setPipelineErrors([]) }

  const filteredItems = useMemo(
    () => filterDashboardItems(query, data.pipelines, data.errors),
    [query, data]
  )

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
                  <span className="db-modal-meta-text">Last run: {selectedPipeline.lastRun}</span>
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
                    <p className="db-error-type">⚠ {item.error}</p>
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

      <header className="db-header">
        <div className="db-header-inner">
          <div className="db-header-left">
            {onBack && <button className="db-back-btn" onClick={onBack}>← Home</button>}
            <span className="db-logo-icon">⚙️</span>
            <span className="db-logo-text">AI Pipeline Debugger</span>
            <span className="db-badge">Dashboard</span>
          </div>
          <div className="db-header-right">
            <span className="db-live-dot" title="Live — polling every 5s" />
            <span className="db-live-label">Live</span>
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
                <p className="db-pipeline-meta">Last run: {pipeline.lastRun}</p>
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
            <span className="db-count-badge">{filteredItems.errors.length}</span>
          </div>
          {filteredItems.errors.length === 0 ? (
            <div className="db-empty"><p>No errors matched your search.</p></div>
          ) : filteredItems.errors.map((item, i) => (
            <div key={i} className="db-analysis-card">
              <p className="db-analysis-pipeline">{item.pipeline}</p>
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
