import { useState } from 'react'

function CopyIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

function CheckIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  )
}

const INGESTION_URL = 'http://localhost:8000/ingest'
const WEBHOOK_URL   = 'http://localhost:8003/webhook'

function snippets(jobId) {
  const id = jobId || 'my-pipeline'
  return {
    airflow: `# In your DAG's default_args:
import requests

def _notify_failure(context):
    requests.post("${WEBHOOK_URL}/airflow", json={
        "dag_id":    context["dag"].dag_id,
        "run_id":    context["run_id"],
        "task_id":   context["task_instance"].task_id,
        "exception": str(context.get("exception", "")),
    }, timeout=5)

default_args = {
    "on_failure_callback": _notify_failure,
    ...
}`,

    spark: `# 1. Start the log agent (watches Spark log output)
python3 services/log-collection-layer/agent.py \\
  --watch-dir /tmp/spark-logs \\
  --job-id    ${id}

# 2. Run your Spark job with stderr redirected to that dir
python3 your_spark_job.py 2>&1 | tee /tmp/spark-logs/${id}.log

# Or use the provided launch script for a ready-made example:
bash services/spark-jobs/run_spark_etl.sh`,

    generic: `curl -X POST ${WEBHOOK_URL}/generic \\
  -H "Content-Type: application/json" \\
  -d '{
    "pipeline": "${id}",
    "level":    "ERROR",
    "message":  "Your error message here",
    "timestamp":"2026-03-09T10:00:00Z"
  }'`,
  }
}

const SOURCE_LABELS = {
  airflow: 'Apache Airflow',
  spark:   'PySpark / Spark Submit',
  generic: 'Generic / Webhook',
}

export default function CreatePipelineForm({ onPipelineCreated }) {
  const [jobId,  setJobId]  = useState('')
  const [source, setSource] = useState('airflow')
  const [copied, setCopied] = useState(false)

  const code = snippets(jobId)[source]

  const handleCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDone = () => {
    if (onPipelineCreated) onPipelineCreated()
  }

  return (
    <div className="card form-card">
      <h3 className="form-title">Connect a Pipeline</h3>
      <p className="muted" style={{ marginBottom: '1rem', fontSize: '0.85rem' }}>
        Pipelines appear automatically once the first event is received.
        Copy the snippet below into your pipeline to start sending live data.
      </p>

      {/* Pipeline name */}
      <div className="form-group">
        <label htmlFor="pipeline-name" className="form-label">Pipeline ID</label>
        <input
          id="pipeline-name"
          className="dashboard-input input-plain"
          placeholder="e.g. spark-customer-ltv-etl"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
        />
        <p className="muted" style={{ fontSize: '0.78rem', marginTop: '0.25rem' }}>
          This becomes the <code>job_id</code> in the debugger — must match what your pipeline sends.
        </p>
      </div>

      {/* Source type tabs */}
      <div className="form-group">
        <label className="form-label">Pipeline Type</label>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {Object.entries(SOURCE_LABELS).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setSource(key)}
              className={`dashboard-button${source === key ? '' : ' btn-ghost'}`}
              style={{ fontSize: '0.8rem', padding: '0.3rem 0.75rem' }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Code snippet */}
      <div className="form-group">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.4rem' }}>
          <label className="form-label" style={{ margin: 0 }}>Integration Snippet</label>
          <button
            type="button"
            className="dashboard-button btn-ghost"
            onClick={handleCopy}
            style={{ fontSize: '0.78rem', padding: '0.25rem 0.6rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
          >
            {copied ? <><CheckIcon /> Copied!</> : <><CopyIcon /> Copy</>}
          </button>
        </div>
        <pre style={{
          background: 'var(--bg-page)',
          color: 'var(--text-muted)',
          borderRadius: 'var(--radius-md)',
          padding: '1rem',
          fontSize: '0.78rem',
          overflowX: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          border: '1px solid var(--border)',
          margin: 0,
        }}>
          {code}
        </pre>
      </div>

      {/* What happens next */}
      <div style={{
        background: 'var(--bg-page)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        padding: '0.75rem 1rem',
        fontSize: '0.8rem',
        color: 'var(--text-secondary)',
        marginBottom: '1rem',
      }}>
        <strong style={{ color: 'var(--text)' }}>What happens next</strong>
        <ol style={{ margin: '0.4rem 0 0', paddingLeft: '1.2rem', lineHeight: 1.7 }}>
          <li>Your pipeline sends an error event to the ingestion API</li>
          <li>The queue worker runs AI analysis via Ollama (llama3.1:8b)</li>
          <li><strong style={{ color: 'var(--text)' }}>{jobId || 'your-pipeline'}</strong> appears here automatically — no manual registration needed</li>
        </ol>
      </div>

      <div className="form-actions">
        <button type="button" className="dashboard-button" onClick={handleDone}>
          Done
        </button>
      </div>
    </div>
  )
}
