import { useState } from "react";

const CHART_SIZES = {
  compact: { width: 560, height: 300 },
  default: { width: 720, height: 300 },
  wide: { width: 1120, height: 300 },
  performance: { width: 960, height: 540 },
};
const MARGIN = { top: 60, right: 22, bottom: 46, left: 72 };

function getChartGeometry(values, width, height) {
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  let min = minValue;
  let max = maxValue;

  if (min === max) {
    const fallbackPadding = Math.max(Math.abs(maxValue) * 0.1, 1);
    min -= fallbackPadding;
    max += fallbackPadding;
  }

  const plotWidth = width - MARGIN.left - MARGIN.right;
  const plotHeight = height - MARGIN.top - MARGIN.bottom;
  const step = values.length > 1 ? plotWidth / (values.length - 1) : 0;
  const valueToY = (value) => MARGIN.top + ((max - value) / (max - min)) * plotHeight;

  const points = values.map((value, index) => ({
    x: MARGIN.left + index * step,
    y: valueToY(value),
  }));

  const yTicks = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    return {
      value: max - ratio * (max - min),
      y: MARGIN.top + ratio * plotHeight,
    };
  });

  return { plotWidth, plotHeight, points, yTicks };
}

function formatTimeLabel(value, firstTimestamp, lastTimestamp) {
  if (value === undefined || value === null || value === "") {
    return "";
  }

  const numericValue = Number(value);
  const date = typeof value === "number" || (typeof value === "string" && /^\d+$/.test(value))
    ? new Date(numericValue * (numericValue < 1_000_000_000_000 ? 1000 : 1))
    : new Date(value);

  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  const span = Math.abs(lastTimestamp - firstTimestamp);
  if (span <= 2 * 24 * 60 * 60 * 1000) {
    return new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  }
  if (span <= 370 * 24 * 60 * 60 * 1000) {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
    }).format(date);
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    year: "2-digit",
  }).format(date);
}

function getTimestampMilliseconds(value) {
  const numericValue = Number(value);
  if (typeof value === "number" || (typeof value === "string" && /^\d+$/.test(value))) {
    return numericValue * (numericValue < 1_000_000_000_000 ? 1000 : 1);
  }
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatHoverTimeLabel(value, firstTimestamp, lastTimestamp, index) {
  if (value === undefined || value === null || value === "") {
    return `Point ${index + 1}`;
  }

  const milliseconds = getTimestampMilliseconds(value);
  if (!milliseconds) {
    return String(value);
  }

  const date = new Date(milliseconds);
  const span = Math.abs(lastTimestamp - firstTimestamp);
  return new Intl.DateTimeFormat("en-US", span <= 2 * 24 * 60 * 60 * 1000
    ? { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }
    : { month: "short", day: "numeric", year: "numeric" }
  ).format(date);
}

function formatAxisValue(value, valueType) {
  if (valueType === "currency") {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  const percentageValue = valueType === "decimalPercent" ? value * 100 : value;
  if (valueType === "percent" || valueType === "decimalPercent") {
    return `${percentageValue.toFixed(2)}%`;
  }

  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export default function EquityChart({
  equity = [],
  timestamps = [],
  valueType = "number",
  variant = "default",
  align = "center",
  ariaLabel = "Account equity chart",
  emptyMessage = "Equity history will appear here once data is available.",
}) {
  const [hoveredIndex, setHoveredIndex] = useState(null);
  const pointsWithLabels = equity
    .map((value, index) => ({ value: Number(value), timestamp: timestamps[index], index }))
    .filter((point) => Number.isFinite(point.value));
  const values = pointsWithLabels.map((point) => point.value);
  const chartSize = CHART_SIZES[variant] || CHART_SIZES.default;
  const chartClassName = `chart-frame chart-frame--${variant}`;

  if (!values.length) {
    return <div className={chartClassName}><div className="chart-empty">{emptyMessage}</div></div>;
  }

  const geometry = getChartGeometry(values, chartSize.width, chartSize.height);
  const path = geometry.points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
  const xTickCount = Math.min(variant === "compact" ? 3 : 5, values.length);
  const xTickIndexes = Array.from({ length: xTickCount }, (_, index) =>
    Math.round((index * (values.length - 1)) / Math.max(xTickCount - 1, 1))
  );
  const firstTimestamp = getTimestampMilliseconds(pointsWithLabels[0]?.timestamp);
  const lastTimestamp = getTimestampMilliseconds(pointsWithLabels.at(-1)?.timestamp);
  const baseline = chartSize.height - MARGIN.bottom;
  const hoveredDatum = hoveredIndex === null ? null : pointsWithLabels[hoveredIndex];
  const hoveredPoint = hoveredIndex === null ? null : geometry.points[hoveredIndex];

  function updateHoveredPoint(event) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const viewBoxX = ((event.clientX - bounds.left) / bounds.width) * chartSize.width;
    const ratio = (viewBoxX - MARGIN.left) / geometry.plotWidth;
    const nextIndex = Math.max(
      0,
      Math.min(values.length - 1, Math.round(ratio * Math.max(values.length - 1, 0)))
    );
    setHoveredIndex(nextIndex);
  }

  function moveKeyboardSelection(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    setHoveredIndex((currentIndex) => Math.max(
      0,
      Math.min(values.length - 1, (currentIndex ?? values.length - 1) + direction)
    ));
  }

  return (
    <div className={chartClassName}>
      {hoveredDatum && (
        <div className="chart-hover-readout" aria-live="polite">
          <strong>{formatAxisValue(hoveredDatum.value, valueType)}</strong>
          <span>{formatHoverTimeLabel(hoveredDatum.timestamp, firstTimestamp, lastTimestamp, hoveredDatum.index)}</span>
        </div>
      )}
      <svg
        viewBox={`0 0 ${chartSize.width} ${chartSize.height}`}
        preserveAspectRatio={align === "left" ? "xMinYMid meet" : "xMidYMid meet"}
        role="img"
        aria-label={ariaLabel}
        tabIndex="0"
        onPointerMove={updateHoveredPoint}
        onPointerLeave={() => setHoveredIndex(null)}
        onFocus={() => setHoveredIndex(values.length - 1)}
        onBlur={() => setHoveredIndex(null)}
        onKeyDown={moveKeyboardSelection}
      >
        <defs>
          <linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="rgba(124, 58, 237, 0.32)" />
            <stop offset="100%" stopColor="rgba(124, 58, 237, 0)" />
          </linearGradient>
        </defs>

        {geometry.yTicks.map((tick) => (
          <g key={tick.y}>
            <line className="chart-grid-line" x1={MARGIN.left} x2={chartSize.width - MARGIN.right} y1={tick.y} y2={tick.y} />
            <text className="chart-axis-label chart-y-label" x={MARGIN.left - 10} y={tick.y + 4}>
              {formatAxisValue(tick.value, valueType)}
            </text>
          </g>
        ))}

        <line className="chart-axis-line" x1={MARGIN.left} x2={MARGIN.left} y1={MARGIN.top} y2={baseline} />
        <line className="chart-axis-line" x1={MARGIN.left} x2={chartSize.width - MARGIN.right} y1={baseline} y2={baseline} />

        <path
          d={`${path} L ${geometry.points.at(-1).x.toFixed(2)} ${baseline} L ${geometry.points[0].x.toFixed(2)} ${baseline} Z`}
          fill="url(#equityFill)"
        />
        <path d={path} fill="none" stroke="#7c3aed" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" />

        {hoveredPoint && (
          <g className="chart-crosshair" aria-hidden="true">
            <line x1={hoveredPoint.x} x2={hoveredPoint.x} y1={MARGIN.top} y2={baseline} />
            <circle cx={hoveredPoint.x} cy={hoveredPoint.y} r="5" />
          </g>
        )}

        {xTickIndexes.map((pointIndex) => {
          const point = geometry.points[pointIndex];
          const datum = pointsWithLabels[pointIndex];
          const label = timestamps.length
            ? formatTimeLabel(datum.timestamp, firstTimestamp, lastTimestamp)
            : String(datum.index + 1);
          return (
            <g key={`${pointIndex}-${label}`}>
              <line className="chart-axis-line" x1={point.x} x2={point.x} y1={baseline} y2={baseline + 5} />
              <text className="chart-axis-label chart-x-label" x={point.x} y={baseline + 23}>{label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
