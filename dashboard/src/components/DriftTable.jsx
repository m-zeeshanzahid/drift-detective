export default function DriftTable({ drifts }) {
  return (
    <table className="drift-table">
      <thead>
        <tr>
          <th>Resource</th><th>Attribute</th>
          <th>Desired</th><th>Actual</th><th>Severity</th>
        </tr>
      </thead>
      <tbody>
        {drifts.map((d, i) => (
          <tr key={i}>
            <td className="resource-id">{d.resource_id}</td>
            <td>{d.attribute}</td>
            <td className="desired-val">{String(d.desired)}</td>
            <td className="actual-val">{String(d.actual)}</td>
            <td>
              <span className={`severity-badge badge-${d.severity}`}>
                {d.severity}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
