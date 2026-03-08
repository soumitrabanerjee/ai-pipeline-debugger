import { useState } from 'react';

export default function CreatePipelineForm({ onPipelineCreated }) {
  const [name, setName] = useState('');
  const [status, setStatus] = useState('Success');
  const [lastRun, setLastRun] = useState('Just now');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:8001/pipelines', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, status, last_run: lastRun }),
      });

      if (!response.ok) {
        throw new Error('Failed to create pipeline. Please try again.');
      }

      // Clear form and notify parent component
      setName('');
      setStatus('Success');
      setLastRun('Just now');
      if (onPipelineCreated) {
        onPipelineCreated();
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="card" style={{ marginTop: '1rem', display: 'grid', gap: '0.75rem' }}>
      <h3>Add New Pipeline</h3>
      {error && <p style={{ color: '#b41b1b' }}>{error}</p>}

      <div style={{ display: 'grid', gap: '0.25rem' }}>
        <label htmlFor="pipeline-name">Pipeline Name</label>
        <input
          id="pipeline-name"
          className="dashboard-input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>

      <div style={{ display: 'grid', gap: '0.25rem' }}>
        <label htmlFor="pipeline-status">Status</label>
        <select
          id="pipeline-status"
          className="dashboard-input"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option>Success</option>
          <option>Failed</option>
        </select>
      </div>

      <div style={{ display: 'grid', gap: '0.25rem' }}>
        <label htmlFor="pipeline-last-run">Last Run</label>
        <input
          id="pipeline-last-run"
          className="dashboard-input"
          value={lastRun}
          onChange={(e) => setLastRun(e.target.value)}
          required
        />
      </div>

      <button type="submit" className="dashboard-button" disabled={submitting}>
        {submitting ? 'Adding...' : 'Add Pipeline'}
      </button>
    </form>
  );
}
