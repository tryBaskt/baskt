function buildPath(values, width, height, padding) {
  if (!values.length) {
    return "";
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? (width - padding * 2) / (values.length - 1) : 0;

  return values
    .map((value, index) => {
      const x = padding + index * step;
      const y = height - padding - ((value - min) / range) * (height - padding * 2);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export default function EquityChart({ equity = [] }) {
  const values = equity.map(Number).filter(Number.isFinite);
  const path = buildPath(values, 720, 260, 24);

  return (
    <div className="chart-frame">
      {values.length ? (
        <svg viewBox="0 0 720 260" role="img" aria-label="Account equity chart">
          <defs>
            <linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="rgba(124, 58, 237, 0.32)" />
              <stop offset="100%" stopColor="rgba(124, 58, 237, 0)" />
            </linearGradient>
          </defs>
          <path d={`${path} L 696 236 L 24 236 Z`} fill="url(#equityFill)" />
          <path d={path} fill="none" stroke="#7c3aed" strokeLinecap="round" strokeWidth="4" />
        </svg>
      ) : (
        <div className="chart-empty">Equity history will appear here once data is available.</div>
      )}
    </div>
  );
}
