import ArchitectureFlow from './components/ArchitectureFlow'
import PipelineHealthTable from './components/PipelineHealthTable'
import IncidentPanel from './components/IncidentPanel'

const incidents = [
  {
    id: 'INC-1042',
    pipeline: 'daily-etl',
    source: 'Airflow',
    severity: 'High',
    status: 'Investigating',
    rootCause: 'Spark executor memory pressure during shuffle'
  },
  {
    id: 'INC-1043',
    pipeline: 'finance-mart',
    source: 'Databricks',
    severity: 'Medium',
    status: 'Mitigated',
    rootCause: 'Expired service principal token'
  },
  {
    id: 'INC-1044',
    pipeline: 'events-stream',
    source: 'Spark',
    severity: 'Critical',
    status: 'Open',
    rootCause: 'Schema drift in upstream event payload'
  }
]

export default function App() {
  return (
    <main className="page">
      <header className="hero">
        <h1>AI Pipeline Debugger</h1>
        <p>
          Unified monitoring and root-cause analysis for Airflow, Spark, and Databricks jobs.
        </p>
      </header>

      <section className="card">
        <h2>Architecture</h2>
        <ArchitectureFlow />
      </section>

      <section className="grid">
        <div className="card">
          <h2>Pipeline Health</h2>
          <PipelineHealthTable incidents={incidents} />
        </div>
        <div className="card">
          <h2>Latest Incident Insight</h2>
          <IncidentPanel incident={incidents[0]} />
        </div>
      </section>
    </main>
  )
}
