import { useEffect, useState } from "react";

const periodOptions = [
  { value: "1D", label: "1D" },
  { value: "1W", label: "1W" },
  { value: "1M", label: "1M" },
  { value: "3M", label: "3M" },
  { value: "1A", label: "1Y" },
];

function normalizeTimestamp(value) {
  const numericValue = Number(value);
  if (Number.isFinite(numericValue)) {
    return numericValue > 10_000_000_000 ? numericValue : numericValue * 1000;
  }

  const parsedDate = new Date(value).getTime();
  return Number.isFinite(parsedDate) ? parsedDate : null;
}

function normalizeEquityPoints(payload) {
  const equity = Array.isArray(payload?.equity) ? payload.equity : [];
  const timestamps = Array.isArray(payload?.timestamp) ? payload.timestamp : [];

  return equity
    .map((value, index) => ({
      equity: Number(value),
      timestamp: normalizeTimestamp(timestamps[index]),
    }))
    .filter((point) => Number.isFinite(point.equity) && point.timestamp !== null);
}

function formatCurrency(value) {
  if (!Number.isFinite(value)) {
    return "-";
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function getLatestNumber(value) {
  if (Array.isArray(value)) {
    return getLatestNumber(value[value.length - 1]);
  }

  const numericValue = Number(value);
  return Number.isFinite(numericValue) ? numericValue : null;
}

function formatPercentage(value) {
  const numericValue = getLatestNumber(value);
  if (numericValue === null) {
    return "-";
  }

  return `${(numericValue * 100).toFixed(2)}%`;
}

function formatChartDate(value) {
  if (!value) {
    return "-";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(new Date(value));
}

function buildEquityPath(points) {
  if (points.length === 0) {
    return "";
  }

  if (points.length === 1) {
    return "M 24 128 L 616 128";
  }

  const width = 640;
  const height = 260;
  const paddingX = 24;
  const paddingY = 28;
  const minEquity = Math.min(...points.map((point) => point.equity));
  const maxEquity = Math.max(...points.map((point) => point.equity));
  const minTime = Math.min(...points.map((point) => point.timestamp));
  const maxTime = Math.max(...points.map((point) => point.timestamp));
  const equityRange = maxEquity - minEquity || 1;
  const timeRange = maxTime - minTime || 1;

  return points
    .map((point, index) => {
      const x = paddingX + ((point.timestamp - minTime) / timeRange) * (width - paddingX * 2);
      const y =
        height -
        paddingY -
        ((point.equity - minEquity) / equityRange) * (height - paddingY * 2);

      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export default function AccountEquityGraph({
  performanceByPeriod,
  isLoading,
  errorMessage,
}) {
  const [selectedPeriod, setSelectedPeriod] = useState("1D");
  const availablePeriods = periodOptions.filter((period) => performanceByPeriod[period.value]);

  useEffect(() => {
    if (availablePeriods.length > 0 && !performanceByPeriod[selectedPeriod]) {
      setSelectedPeriod(availablePeriods[0].value);
    }
  }, [availablePeriods, performanceByPeriod, selectedPeriod]);

  const selectedPerformance = performanceByPeriod[selectedPeriod] || {};
  const equityPoints = normalizeEquityPoints(selectedPerformance);
  const chartPath = buildEquityPath(equityPoints);
  const latestPoint = equityPoints[equityPoints.length - 1];
  const firstPoint = equityPoints[0];
  const profitLoss = getLatestNumber(selectedPerformance.profit_loss);

  function handlePeriodSelect(period) {
    setSelectedPeriod(period);
  }

  return (
    <div className="account-performance-panel">
      <div className="account-performance-header">
        <div>
          <h1 id="home-title">Account Equity</h1>
          <p>
            {latestPoint
              ? `${formatChartDate(firstPoint.timestamp)} - ${formatChartDate(latestPoint.timestamp)}`
              : "Portfolio history"}
          </p>
        </div>
        <strong>{formatCurrency(latestPoint?.equity)}</strong>
      </div>

      <div className="account-period-controls" aria-label="Account performance period">
        {periodOptions.map((period) => (
          <button
            key={period.value}
            type="button"
            className={selectedPeriod === period.value ? "is-selected" : ""}
            onClick={() => handlePeriodSelect(period.value)}
            disabled={!performanceByPeriod[period.value]}
          >
            {period.label}
          </button>
        ))}
      </div>

      {isLoading ? <p className="account-performance-meta">Loading account equity...</p> : null}
      {errorMessage ? <p className="account-performance-error">{errorMessage}</p> : null}
      {!isLoading && !errorMessage && availablePeriods.length === 0 ? (
        <p className="account-performance-meta">No account equity history available.</p>
      ) : null}

      {!isLoading && !errorMessage && availablePeriods.length > 0 ? (
        <div className="account-performance-metrics">
          <div>
            <span>Profit/Loss</span>
            <strong className={profitLoss >= 0 ? "is-positive" : "is-negative"}>
              {formatCurrency(profitLoss)}
            </strong>
          </div>
          <div>
            <span>Profit/Loss %</span>
            <strong className={profitLoss >= 0 ? "is-positive" : "is-negative"}>
              {formatPercentage(selectedPerformance.profit_loss_pct)}
            </strong>
          </div>
          <div>
            <span>Base Value</span>
            <strong>{formatCurrency(getLatestNumber(selectedPerformance.base_value))}</strong>
          </div>
        </div>
      ) : null}

      {equityPoints.length > 0 ? (
        <svg
          viewBox="0 0 640 260"
          className="account-equity-chart"
          role="img"
          aria-label="Account equity over time"
        >
          <line x1="24" y1="232" x2="616" y2="232" className="account-equity-axis" />
          <line x1="24" y1="28" x2="24" y2="232" className="account-equity-axis" />
          <path d={chartPath} className="account-equity-line" />
        </svg>
      ) : null}
    </div>
  );
}
