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
    <form onSubmit={handleSubmit} className="card form-card">
      <h3 className="form-title">Add New Pipeline</h3>

      {error && (
        <p className="form-error">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          {error}
        </p>
      )}

      <div className="form-group">
        <label htmlFor="pipeline-name" className="form-label">Pipeline Name</label>
        <input
          id="pipeline-name"
          className="dashboard-input input-plain"
          placeholder="e.g. customer_etl"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>

      <div className="form-group">
        <label htmlFor="pipeline-status" className="form-label">Status</label>
        <select
          id="pipeline-status"
          className="form-select"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option>Success</option>
          <option>Failed</option>
        </select>
      </div>

      <div className="form-group">
        <label htmlFor="pipeline-last-run" className="form-label">Last Run</label>
        <input
          id="pipeline-last-run"
          className="dashboard-input input-plain"
          placeholder="e.g. 5 min ago"
          value={lastRun}
          onChange={(e) => setLastRun(e.target.value)}
          required
        />
      </div>

      <div className="form-actions">
        <button
          type="submit"
          className="dashboard-button"
          disabled={submitting}
        >
          {submitting ? 'Adding...' : 'Create Pipeline'}
        </button>
      </div>
    </form>
  );
}
