import { useState, useEffect } from 'react';
import EnvironmentCard from './components/EnvironmentCard';
import './index.css';

const ENVIRONMENTS = ['prod', 'dev'];

export default function App() {
  const [runs, setRuns]               = useState([]);
  const [loading, setLoading]         = useState(true);
  const [triggering, setTriggering]   = useState(false);
  const [lastRefresh, setLastRefresh] = useState(null);

  const fetchRuns = async () => {
    try {
      const res  = await fetch('/api/runs');
      const data = await res.json();
      setRuns(Array.isArray(data) ? data : data.runs || []);
      setLastRefresh(new Date());
    } catch (err) {
      console.error('Failed to fetch runs:', err);
    } finally {
      setLoading(false);
    }
  };

  const triggerScan = async () => {
    setTriggering(true);
    try {
      await fetch('/api/trigger', { method: 'POST' });
      setTimeout(fetchRuns, 3000);
    } catch (err) {
      console.error('Trigger failed:', err);
    } finally {
      setTimeout(() => setTriggering(false), 3000);
    }
  };

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 30000);
    return () => clearInterval(interval);
  }, []);

  const getEnvData = (env) => {
    const envRuns = runs.filter(r =>
      r.inputs?.environment === env || r.name?.includes(env)
    );
    if (!envRuns.length) return { status: 'unknown', run: null };
    const latest = envRuns[0];
    const output = latest.outputs || {};
    return {
      status:        output.classification || latest.status || 'unknown',
      run:           latest,
      drifts:        output.drifts || [],
      drift_count:   output.drift_count || 0,
      drift_summary: output.drift_summary || '',
      checked_at:    output.checked_at || latest.created_at
    };
  };

  const overallStatus = ENVIRONMENTS.some(e => getEnvData(e).status === 'critical')
    ? 'critical'
    : ENVIRONMENTS.some(e => getEnvData(e).status === 'suspicious')
    ? 'suspicious'
    : 'safe';

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <h1>Drift Detective</h1>
          <span className={`overall-badge badge-${overallStatus}`}>
            {overallStatus.toUpperCase()}
          </span>
        </div>
        <div className="header-right">
          {lastRefresh && (
            <span className="last-refresh">
              Last refresh: {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button onClick={triggerScan} disabled={triggering} className="btn-scan">
            {triggering ? 'Scanning...' : '⚡ Run Scan Now'}
          </button>
        </div>
      </header>
      <main className="main">
        {loading ? (
          <div className="loading">Connecting to SuperPlane...</div>
        ) : (
          <div className="env-grid">
            {ENVIRONMENTS.map(env => {
              const d = getEnvData(env);
              return (
                <EnvironmentCard key={env} environment={env} {...d} />
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
