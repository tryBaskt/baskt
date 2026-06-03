import { useEffect, useMemo, useState } from "react";

import "./HomePage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

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

export default function HomePage() {
  const [equityPoints, setEquityPoints] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const token = useMemo(
    () => sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "",
    []
  );

  useEffect(() => {
    let isCancelled = false;

    async function fetchAccountPerformance() {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const response = await fetch(`${API_BASE_URL}/account-performance/account-id`, {
          method: "GET",
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload?.detail || `Failed to load account performance (${response.status}).`);
        }

        if (!isCancelled) {
          setEquityPoints(normalizeEquityPoints(payload));
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(error?.message || "Unable to load account performance.");
          setEquityPoints([]);
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    fetchAccountPerformance();

    return () => {
      isCancelled = true;
    };
  }, [token]);

  const chartPath = buildEquityPath(equityPoints);
  const latestPoint = equityPoints[equityPoints.length - 1];
  const firstPoint = equityPoints[0];

  return (
    <section className="account-performance-page" aria-labelledby="home-title">
      <div className="account-performance-panel">
        <div className="account-performance-header">
          <div>
            <h1 id="home-title">Account Equity</h1>
            <p>{latestPoint ? `${formatChartDate(firstPoint.timestamp)} - ${formatChartDate(latestPoint.timestamp)}` : "Portfolio history"}</p>
          </div>
          <strong>{formatCurrency(latestPoint?.equity)}</strong>
        </div>

        {isLoading ? <p className="account-performance-meta">Loading account equity...</p> : null}
        {errorMessage ? <p className="account-performance-error">{errorMessage}</p> : null}
        {!isLoading && !errorMessage && equityPoints.length === 0 ? (
          <p className="account-performance-meta">No account equity history available.</p>
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
    </section>
  );
}
