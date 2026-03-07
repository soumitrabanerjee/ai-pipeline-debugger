const layers = [
  'Customer Pipelines (Airflow / Spark / Databricks)',
  'Log Collection Layer (Webhook / Agent / API Pull)',
  'Log Ingestion API (FastAPI)',
  'Message Queue (Kafka / Redis Streams)',
  'Log Storage (S3 + PostgreSQL metadata)',
  'Log Processing Layer (Parser + Error Extractor)',
  'AI Debugging Engine (RAG + Vector DB)',
  'Root Cause Engine',
  'API Layer',
  'Web Dashboard + Slack Alerts'
]

export default function ArchitectureFlow() {
  return (
    <ol className="flow">
      {layers.map((layer) => (
        <li key={layer}>{layer}</li>
      ))}
    </ol>
  )
}
