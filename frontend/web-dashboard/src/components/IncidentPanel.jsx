export default function IncidentPanel({ incident }) {
  return (
    <article className="incident">
      <p className="incident-id">{incident.id}</p>
      <h3>{incident.pipeline}</h3>
      <p>
        <strong>Detected in:</strong> {incident.source}
      </p>
      <p>
        <strong>Root Cause:</strong> {incident.rootCause}
      </p>
      <p className="recommendation">
        Recommendation: Increase executor memory, rebalance partitions, and re-run failed tasks.
      </p>
    </article>
  )
}
