const LABELS = {
  safe: '✓ Safe', suspicious: '⚠ Suspicious',
  critical: '🔴 Critical', unknown: '? Unknown', running: '⟳ Scanning'
};

export default function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${status}`}>
      {LABELS[status] || status}
    </span>
  );
}
