function formatFractionWeight(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "0.00%";
  }

  return `${(numeric * 100).toFixed(2)}%`;
}

function formatPercentPriceChange(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "Not available";
  }

  const formatted = `${(numeric * 100).toFixed(2)}%`;
  return numeric > 0 ? `+${formatted}` : formatted;
}

function getPercentPriceChangeTone(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "";
  }
  return numeric >= 0 ? "positive" : "negative";
}

export default function PositionsTable({
  positions = [],
  currentWeights = {},
  currentPercentPriceChanges = {},
  showCurrentWeight = false,
  showPercentPriceChange = false,
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Target</th>
            {showCurrentWeight ? <th>Current</th> : null}
            <th>Side</th>
            <th>Leverage</th>
            {showPercentPriceChange ? <th>PCT Change</th> : null}
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => {
            const percentPriceChange = currentPercentPriceChanges[position.symbol];
            return (
              <tr key={`${position.symbol}-${position.direction}`}>
                <td>
                  <strong>{position.symbol}</strong>
                </td>
                <td>{formatFractionWeight(position.target_weight)}</td>
                {showCurrentWeight ? (
                  <td>{formatFractionWeight(currentWeights[position.symbol] || 0)}</td>
                ) : null}
                <td>
                  <span className={position.direction === -1 ? "pill danger" : "pill"}>
                    {position.direction === -1 ? "Short" : "Long"}
                  </span>
                </td>
                <td>{position.leverage || 1}x</td>
                {showPercentPriceChange ? (
                  <td
                    className={getPercentPriceChangeTone(percentPriceChange)}
                    title="Percent price change compares the latest market price with this position's filled average price."
                  >
                    {formatPercentPriceChange(percentPriceChange)}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
