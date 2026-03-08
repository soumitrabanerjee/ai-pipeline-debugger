import { useEffect, useMemo, useState } from 'react'
import { filterDashboardItems } from './dashboardData'
import CreatePipelineForm from './CreatePipelineForm'

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
      if (!response.ok) {
        throw new Error('Failed to fetch dashboard data')
      }
      const result = await response.json()
      setData(result)
      setError(null) // Clear error if fetch succeeds
    } catch (err) {
      console.error(err)
      // Only set error state if we don't have data yet, to avoid flashing error on transient failures
      if (data.pipelines.length === 0) {
        setError(err.message)
      }
    } finally {
      if (isInitial) setLoading(false)
    }
  }

  useEffect(() => {
    // Initial fetch
    fetchData(true)

    // Poll every 5 seconds
    const intervalId = setInterval(() => {
      fetchData(false)
    }, 5000)

    // Cleanup interval on unmount
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

  // Apply saved theme on first render
  useEffect(() => {
    document.body.setAttribute('data-theme', darkMode ? 'dark' : '')
  }, [])

  const filteredItems = useMemo(
    () => filterDashboardItems(query, data.pipelines, data.errors),
    [query, data]
  )

  if (loading && !data.pipelines.length) return <div className="dashboard-page">Loading...</div>
  if (error && !data.pipelines.length) return <div className="dashboard-page">Error: {error}</div>

  return (
    <>
    {selectedPipeline && (
      <div className="modal-overlay" onClick={handleCloseDetail}>
        <div className="modal-content" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            <h2>{selectedPipeline.name}</h2>
            <button className="modal-close" onClick={handleCloseDetail}>✕</button>
          </div>
          <p className="muted">Last run: {selectedPipeline.lastRun} &nbsp;|&nbsp;
            <span className={selectedPipeline.status === 'Failed' ? 'status-chip failed' : 'status-chip success'}>
              {selectedPipeline.status}
            </span>
          </p>
          <h3>Error History</h3>
          {detailLoading ? (
            <p>Loading errors...</p>
          ) : pipelineErrors.length === 0 ? (
            <p className="empty-state">No errors recorded for this pipeline.</p>
          ) : (
            <div className="dashboard-list">
              {pipelineErrors.map((item, i) => (
                <article key={i} className="card">
                  <p className="error-text">Error: {item.error}</p>
                  <p>Root Cause: {item.rootCause}</p>
                  <p className="fix-text">Suggested Fix: {item.fix}</p>
                </article>
              ))}
            </div>
          )}
        </div>
      </div>
    )}
    <main className="dashboard-page">
      <h1>AI Data Pipeline Debugger</h1>

      <div className="search-row">
        <input
          aria-label="Search pipelines or errors"
          className="dashboard-input"
          placeholder="Search pipelines or errors..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="button" className="dashboard-button" aria-label="Search">
          🔍
        </button>
        <button
          type="button"
          className="dashboard-button"
          style={{ width: 'auto', padding: '0 1rem' }}
          onClick={() => setShowCreateForm(!showCreateForm)}
        >
          {showCreateForm ? 'Cancel' : 'Add Pipeline'}
        </button>
        <button
          type="button"
          className="theme-toggle"
          aria-label="Toggle dark mode"
          onClick={toggleDarkMode}
          title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {darkMode ? '☀️' : '🌙'}
        </button>
      </div>

      {showCreateForm && (
        <CreatePipelineForm onPipelineCreated={handlePipelineCreated} />
      )}

      <section className="stats-grid" aria-label="Dashboard summary">
        <article className="card stat-card">
          <h2>Total Pipelines</h2>
          <p className="stat-value">{data.pipelines.length}</p>
        </article>

        <article className="card stat-card">
          <h2>Failures Today</h2>
          <p className="stat-value">
            {data.pipelines.filter((p) => p.status === 'Failed').length}
          </p>
        </article>

        <article className="card stat-card">
          <h2>MTTR</h2>
          <p className="stat-value">12 min</p>
        </article>
      </section>

      <section>
        <h2>Pipeline Status</h2>
        <div className="dashboard-list">
          {filteredItems.pipelines.map((pipeline) => (
            <article
              key={pipeline.name}
              className="card status-card clickable"
              onClick={() => handlePipelineClick(pipeline)}
              title="Click to view error history"
            >
              <div>
                <p className="pipeline-name">{pipeline.name}</p>
                <p className="muted">Last run: {pipeline.lastRun}</p>
              </div>
              <span
                className={
                  pipeline.status === 'Failed' ? 'status-chip failed' : 'status-chip success'
                }
              >
                {pipeline.status}
              </span>
            </article>
          ))}
          {filteredItems.pipelines.length === 0 && (
            <p className="empty-state">No pipelines matched your search.</p>
          )}
        </div>
      </section>

      <section>
        <h2>AI Root Cause Analysis</h2>
        <div className="dashboard-list">
          {filteredItems.errors.map((item) => (
            <article key={`${item.pipeline}-${item.error}`} className="card">
              <p className="pipeline-name">Pipeline: {item.pipeline}</p>
              <p className="error-text">Error: {item.error}</p>
              <p>Root Cause: {item.rootCause}</p>
              <p className="fix-text">Suggested Fix: {item.fix}</p>
            </article>
          ))}
          {filteredItems.errors.length === 0 && (
            <p className="empty-state">No errors matched your search.</p>
          )}
        </div>
      </section>
    </main>
    </>
  )
}
