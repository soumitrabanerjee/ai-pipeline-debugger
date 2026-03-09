import { useState } from 'react'

function CopyIcon() {
  return (
    <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

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
python3 your_spark_job.py 2>&1 | tee /tmp/spark-logs/${id}.log`,
    generic: `curl -X POST ${WEBHOOK_URL}/generic \\
  -H "Content-Type: application/json" \\
  -d '{
    "pipeline": "${id}",
    "level":    "ERROR",
    "message":  "Your error message here",
    "timestamp":"2026-03-10T10:00:00Z"
  }'`,
  }
}

const SOURCE_LABELS = {
  airflow: 'Apache Airflow',
  spark:   'PySpark / Spark',
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

  return (
    <div className="db-form-card">
      <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#f1f5f9', margin: '0 0 0.3rem' }}>
        Connect a Pipeline
      </h3>
      <p style={{ fontSize: '0.825rem', color: '#64748b', margin: '0 0 1.5rem', lineHeight: 1.6 }}>
        Pipelines appear automatically once the first event is received. Copy the snippet below into your pipeline.
      </p>

      {/* Pipeline ID */}
      <div style={{ marginBottom: '1.25rem' }}>
        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.4rem' }}>
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
        <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.4rem' }}>
          Pipeline Type
        </label>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          {Object.entries(SOURCE_LABELS).map(([key, label]) => (
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
          <label style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
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
          background: 'rgba(0,0,0,0.4)',
          border: '1px solid rgba(255,255,255,0.07)',
          borderRadius: '10px',
          padding: '1rem 1.25rem',
          fontSize: '0.75rem',
          fontFamily: "'Fira Code', 'SF Mono', Consolas, monospace",
          color: '#94a3b8',
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
        background: 'rgba(99,102,241,0.05)',
        border: '1px solid rgba(99,102,241,0.15)',
        borderRadius: '10px',
        padding: '0.875rem 1rem',
        fontSize: '0.8rem',
        color: '#94a3b8',
        lineHeight: 1.65,
        marginBottom: '1.25rem',
      }}>
        <strong style={{ color: '#f1f5f9', display: 'block', marginBottom: '0.4rem' }}>What happens next</strong>
        <ol style={{ margin: 0, paddingLeft: '1.2rem' }}>
          <li>Your pipeline sends an error event to the ingestion API</li>
          <li>The queue worker runs AI analysis via Ollama (llama3.1:8b)</li>
          <li><strong style={{ color: '#f1f5f9' }}>{jobId || 'your-pipeline'}</strong> appears in the dashboard automatically</li>
        </ol>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button type="button" className="lp-btn-primary" onClick={onPipelineCreated}>Done</button>
      </div>
    </div>
  )
}
