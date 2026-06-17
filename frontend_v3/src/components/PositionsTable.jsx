function formatPercentUnits(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "0.00%";
  }

  return `${numeric.toFixed(2)}%`;
}

function formatFractionWeight(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "0.00%";
  }

  return `${(numeric * 100).toFixed(2)}%`;
}

export default function PositionsTable({ positions = [], currentWeights = {} }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Target</th>
            <th>Current</th>
            <th>Side</th>
            <th>Leverage</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={`${position.symbol}-${position.direction}`}>
              <td>
                <strong>{position.symbol}</strong>
              </td>
              <td>{formatPercentUnits(position.target_weight)}</td>
              <td>{formatFractionWeight(currentWeights[position.symbol] || 0)}</td>
              <td>
                <span className={position.direction === -1 ? "pill danger" : "pill"}>
                  {position.direction === -1 ? "Short" : "Long"}
                </span>
              </td>
              <td>{position.leverage || 1}x</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
