import StatusBadge from './StatusBadge';
import DriftTable from './DriftTable';

const REGION_MAP = { prod: 'us-east-1', dev: 'us-east-1' };

export default function EnvironmentCard({
  environment, status, run, drifts = [], drift_count = 0, drift_summary, checked_at
}) {
  return (
    <div className={`env-card card-${status}`}>
      <div className="card-header">
        <div>
          <h2 className="env-name">{environment.toUpperCase()}</h2>
          <span className="region-label">{REGION_MAP[environment]}</span>
        </div>
        <StatusBadge status={status} />
      </div>

      <div className="card-body">
        {drift_count > 0 ? (
          <>
            <p className="drift-count">
              {drift_count} drift{drift_count !== 1 ? 's' : ''} detected
            </p>
            {drifts.length > 0 && <DriftTable drifts={drifts} />}
            {drift_summary && (
              <details className="summary-details">
                <summary>Claude's analysis</summary>
                <pre className="summary-text">{drift_summary}</pre>
              </details>
            )}
          </>
        ) : (
          <p className="no-drift">
            {status === 'unknown' ? 'No scan data yet' : '✓ No drift detected'}
          </p>
        )}
      </div>

      <div className="card-footer">
        {checked_at && (
          <span className="checked-at">
            Scanned: {new Date(checked_at).toLocaleTimeString()}
          </span>
        )}
        {run?.id && (
          <a href="https://app.superplane.com" target="_blank" rel="noreferrer"
             className="view-run-link">
            View run →
          </a>
        )}
      </div>
    </div>
  );
}
