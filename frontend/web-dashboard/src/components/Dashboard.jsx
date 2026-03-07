import { useMemo, useState } from 'react'
import { filterDashboardItems } from './dashboardData'

export default function Dashboard() {
  const [query, setQuery] = useState('')

  const filteredItems = useMemo(() => filterDashboardItems(query), [query])

  return (
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
      </div>

      <section className="stats-grid" aria-label="Dashboard summary">
        <article className="card stat-card">
          <h2>Total Pipelines</h2>
          <p className="stat-value">24</p>
        </article>

        <article className="card stat-card">
          <h2>Failures Today</h2>
          <p className="stat-value">6</p>
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
            <article key={pipeline.name} className="card status-card">
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
  )
}
