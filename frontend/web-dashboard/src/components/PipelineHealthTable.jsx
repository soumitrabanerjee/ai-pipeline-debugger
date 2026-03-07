export default function PipelineHealthTable({ incidents }) {
  return (
    <table className="status-table">
      <thead>
        <tr>
          <th>Incident</th>
          <th>Pipeline</th>
          <th>Source</th>
          <th>Severity</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {incidents.map((incident) => (
          <tr key={incident.id}>
            <td>{incident.id}</td>
            <td>{incident.pipeline}</td>
            <td>{incident.source}</td>
            <td>{incident.severity}</td>
            <td>{incident.status}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
