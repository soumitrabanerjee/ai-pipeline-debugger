import { useState } from 'react'
import { WEBHOOK_URL, INGEST_URL } from '../config'

function CopyIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

const WEBHOOK_BASE = WEBHOOK_URL
const INGEST_BASE  = INGEST_URL

function snippets(jobId) {
  const id = jobId || 'my-pipeline'
  return {
    airflow: `# airflow/dags/${id}_dag.py
import requests
from airflow import DAG
from datetime import datetime

PIPLEX_URL    = "${WEBHOOK_BASE}/airflow"
PIPLEX_API_KEY = "YOUR_API_KEY"   # from Dashboard → API Keys

def _on_failure(context):
    """Send failure event to PiPlex for AI root-cause analysis."""
    requests.post(
        PIPLEX_URL,
        headers={"x-api-key": PIPLEX_API_KEY},
        json={
            "dag_id":    context["dag"].dag_id,
            "run_id":    context["run_id"],
            "task_id":   context["task_instance"].task_id,
            "exception": str(context.get("exception", "Unknown error")),
        },
        timeout=5,
    )

with DAG(
    dag_id="${id}",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    default_args={"on_failure_callback": _on_failure},
    catchup=False,
) as dag:
    # your tasks here
    pass`,

    spark: `# ── Option A: Log Agent (file-watcher, recommended) ──────────────

# Terminal 1 — start the agent; it watches for ERROR lines in real time
python3 services/log-collection-layer/agent.py \\
  --watch-dir  /tmp/spark-logs \\
  --job-id     ${id} \\
  --ingest-url ${INGEST_BASE} \\
  --api-key    YOUR_API_KEY

# Terminal 2 — run your PySpark job and tee stderr to the watched dir
spark-submit your_job.py 2>&1 | tee /tmp/spark-logs/${id}.log


# ── Option B: Generic webhook (one-liner, no agent needed) ────────

curl -X POST ${WEBHOOK_BASE}/generic \\
  -H "x-api-key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "pipeline": "${id}",
    "level":    "ERROR",
    "message":  "PythonException: ValueError: could not convert string to float"
  }'`,

    generic: `# Works with any tool that can HTTP POST — no SDK required.

# curl
curl -X POST ${WEBHOOK_BASE}/generic \\
  -H "x-api-key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "pipeline": "${id}",
    "level":    "ERROR",
    "message":  "Your error message here"
  }'

# Python
import requests
requests.post(
    "${WEBHOOK_BASE}/generic",
    headers={"x-api-key": "YOUR_API_KEY"},
    json={
        "pipeline": "${id}",
        "level":    "ERROR",
        "message":  "Your error message here",
    },
    timeout=5,
)`,

    prefect: `# prefect_flow.py
import requests
from prefect import flow

PIPLEX_URL     = "${WEBHOOK_BASE}/generic"
PIPLEX_API_KEY = "YOUR_API_KEY"   # from Dashboard → API Keys

def _notify_failure(flow_name: str, run_id: str, error: str):
    requests.post(
        PIPLEX_URL,
        headers={"x-api-key": PIPLEX_API_KEY},
        json={
            "pipeline": flow_name,
            "run_id":   run_id,
            "level":    "ERROR",
            "message":  error,
        },
        timeout=5,
    )

@flow(name="${id}")
def my_flow():
    try:
        # your Prefect tasks here
        pass
    except Exception as e:
        import prefect.runtime.flow_run as fr
        _notify_failure("${id}", str(fr.id), str(e))
        raise`,
  }
}

const SOURCES = [
  { key: 'airflow', label: '🌬️ Apache Airflow' },
  { key: 'spark',   label: '⚡ PySpark / Spark' },
  { key: 'generic', label: '🔗 Generic / curl'  },
  { key: 'prefect', label: '🔷 Prefect'          },
]

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

  return (
    <div className="db-form-card">
      <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text)', margin: '0 0 0.3rem' }}>
        Connect a Pipeline
      </h3>
      <p style={{ fontSize: '0.825rem', color: 'var(--text-muted)', margin: '0 0 1.5rem', lineHeight: 1.6 }}>
        Pipelines appear automatically once the first event is received. Copy the snippet for your stack.
      </p>

      {/* Pipeline ID */}
      <div style={{ marginBottom: '1.25rem' }}>
        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.4rem' }}>
          Pipeline ID
        </label>
        <input
          className="db-search-input"
          placeholder="e.g. spark-customer-ltv-etl"
          value={jobId}
          onChange={e => setJobId(e.target.value)}
          style={{ paddingLeft: '1rem' }}
        />
      </div>

      {/* Source tabs */}
      <div style={{ marginBottom: '1.25rem' }}>
        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.5rem' }}>
          Pipeline Type
        </label>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {SOURCES.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => setSource(key)}
              className={source === key ? 'lp-btn-primary' : 'lp-btn-ghost'}
              style={{ fontSize: '0.8rem', padding: '0.35rem 0.9rem' }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Code snippet */}
      <div style={{ marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <label style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Integration Snippet
          </label>
          <button
            type="button"
            className="lp-btn-ghost"
            onClick={handleCopy}
            style={{ fontSize: '0.78rem', padding: '0.25rem 0.65rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}
          >
            {copied ? '✓ Copied!' : <><CopyIcon /> Copy</>}
          </button>
        </div>
        <pre style={{
          background: 'var(--bg-input)',
          border: '1px solid var(--border)',
          borderRadius: '10px',
          padding: '1rem 1.25rem',
          fontSize: '0.75rem',
          fontFamily: "'Fira Code', 'SF Mono', Consolas, monospace",
          color: 'var(--text-secondary)',
          overflowX: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          lineHeight: 1.65,
          margin: 0,
        }}>
          {code}
        </pre>
      </div>

      {/* What happens next */}
      <div style={{
        background: 'var(--accent-subtle)',
        border: '1px solid rgba(99,102,241,0.2)',
        borderRadius: '10px',
        padding: '0.875rem 1rem',
        fontSize: '0.8rem',
        color: 'var(--text-secondary)',
        lineHeight: 1.65,
        marginBottom: '1.25rem',
      }}>
        <strong style={{ color: 'var(--text)', display: 'block', marginBottom: '0.4rem' }}>What happens next</strong>
        <ol style={{ margin: 0, paddingLeft: '1.2rem' }}>
          <li>Your pipeline sends an error event to the PiPlex ingestion API</li>
          <li>The queue worker runs AI root-cause analysis via Claude (claude-haiku-4-5)</li>
          <li><strong style={{ color: 'var(--text)' }}>{jobId || 'your-pipeline'}</strong> appears in the dashboard with a fix suggestion</li>
        </ol>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button type="button" className="lp-btn-primary" onClick={onPipelineCreated}>Done</button>
      </div>
    </div>
  )
}
