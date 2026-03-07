import { useMemo, useState } from 'react'
import { Card, CardContent } from './ui/card'
import { Button } from './ui/button'
import { Input } from './ui/input'
import { Search } from './icons/Search'
import { filterDashboardItems } from './dashboardData'

export default function Dashboard() {
  const [query, setQuery] = useState('')
  const filteredItems = useMemo(() => filterDashboardItems(query), [query])

  return (
    <div className="dashboard-page">
      <h1 className="dashboard-title">AI Data Pipeline Debugger</h1>

      <div className="search-row">
        <Input
          placeholder="Search pipelines or errors..."
          aria-label="Search pipelines or errors"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Button aria-label="Search">
          <Search size={16} />
        </Button>
      </div>

      <div className="stats-grid">
        <Card>
          <CardContent className="card-content">
            <h2 className="card-title">Total Pipelines</h2>
            <p className="stat-value">24</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="card-content">
            <h2 className="card-title">Failures Today</h2>
            <p className="stat-value">6</p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="card-content">
            <h2 className="card-title">MTTR</h2>
            <p className="stat-value">12 min</p>
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="section-title">Pipeline Status</h2>
        <div className="dashboard-list">
          {filteredItems.pipelines.map((pipeline) => (
            <Card key={pipeline.name}>
              <CardContent className="pipeline-row">
                <div>
                  <p className="pipeline-name">{pipeline.name}</p>
                  <p className="muted">Last run: {pipeline.lastRun}</p>
                </div>
                <span className={`status-chip ${pipeline.status === 'Failed' ? 'failed' : 'success'}`}>
                  {pipeline.status}
                </span>
              </CardContent>
            </Card>
          ))}
          {filteredItems.pipelines.length === 0 && (
            <p className="empty-state">No pipelines matched your search.</p>
          )}
        </div>
      </div>

      <div>
        <h2 className="section-title">AI Root Cause Analysis</h2>
        <div className="dashboard-list">
          {filteredItems.errors.map((item) => (
            <Card key={`${item.pipeline}-${item.error}`}>
              <CardContent className="card-content">
                <p className="pipeline-name">Pipeline: {item.pipeline}</p>
                <p className="error-text">Error: {item.error}</p>
                <p className="root-cause">Root Cause: {item.rootCause}</p>
                <p className="fix-text">Suggested Fix: {item.fix}</p>
              </CardContent>
            </Card>
          ))}
          {filteredItems.errors.length === 0 && <p className="empty-state">No errors matched your search.</p>}
        </div>
      </div>
    </div>
  )
}
