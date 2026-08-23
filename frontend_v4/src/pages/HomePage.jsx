import { useEffect, useState } from "react";
import EquityChart from "../components/EquityChart";
import { ErrorBanner, LoadingState } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { currency, percent } from "../lib/format";

const periods = ["1D", "1W", "1M", "3M", "1A", "ALL"];
const periodMoveLabels = {
  "1D": "today",
  "1W": "1W",
  "1M": "1M",
  "3M": "3M",
  "1A": "1A",
  ALL: "all time",
};

function formatAllocationType(value) {
  const normalized = String(value || "").toUpperCase();
  if (normalized === "MODEL_PORTFOLIO") {
    return "Baskt";
  }
  if (normalized === "STOCK") {
    return "Stock";
  }
  return "Investment";
}

function signedCurrency(value) {
  if (!Number.isFinite(value)) {
    return "Not available";
  }
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${currency(Math.abs(value))}`;
}

function formatDirection(value) {
  const direction = Number(value);
  if (direction > 0) {
    return "Long";
  }
  if (direction < 0) {
    return "Short";
  }
  return "";
}

function extractOneDayCumulativeReturn(payload) {
  const value = payload?.["1D"]?.final_cumulative_return;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric * 100 : null;
}

function formatReturnChip(value) {
  if (!Number.isFinite(value)) {
    return "N/A";
  }
  return `${value > 0 ? "+" : ""}${percent(value)}`;
}

function getReturnTone(value) {
  if (!Number.isFinite(value)) {
    return "";
  }
  return value >= 0 ? "positive" : "negative";
}

export default function HomePage({ onOpenInvestment }) {
  const [analytics, setAnalytics] = useState(null);
  const [allocationReturns, setAllocationReturns] = useState({});
  const [period, setPeriod] = useState("1D");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let ignore = false;

    async function loadAnalytics() {
      try {
        setIsLoading(true);
        const payload = await apiRequest("/allocation_analytics");
        if (!ignore) {
          setAnalytics(payload);
          setAllocationReturns({});
          const availablePeriods = Object.keys(payload?.equity_graph || {});
          if (availablePeriods.length && !availablePeriods.includes(period)) {
            setPeriod(availablePeriods[0]);
          }
        }

        const portfolioRequests = Object.entries(payload?.portfolio_allocations || {}).map(
          async ([allocationId]) => {
            const analyticsPayload = await apiRequest(
              `/model-portfolios/${encodeURIComponent(allocationId)}/analytics${toQuery({ periods: ["1D"] })}`
            );
            return [allocationId, extractOneDayCumulativeReturn(analyticsPayload)];
          }
        );
        const stockRequests = Object.entries(payload?.stock_allocations || {}).map(
          async ([allocationId, allocation]) => {
            const symbol = allocation?.stock_symbol;
            if (!symbol) {
              return [allocationId, null];
            }
            const analyticsPayload = await apiRequest(
              `/stock-analytics/${encodeURIComponent(symbol)}${toQuery({ periods: ["1D"] })}`
            );
            return [allocationId, extractOneDayCumulativeReturn(analyticsPayload)];
          }
        );
        const settledReturns = await Promise.allSettled([
          ...portfolioRequests,
          ...stockRequests,
        ]);
        if (!ignore) {
          setAllocationReturns(
            Object.fromEntries(
              settledReturns
                .filter((result) => result.status === "fulfilled")
                .map((result) => result.value)
            )
          );
        }
      } catch (analyticsError) {
        if (!ignore) {
          setError(analyticsError?.message || "Could not load account analytics.");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    loadAnalytics();
    return () => {
      ignore = true;
    };
  }, []);

  const selectedGraph = analytics?.equity_graph?.[period] || analytics?.equity_graph?.[period.toLowerCase()];
  const availablePeriods = periods.filter(
    (item) => analytics?.equity_graph?.[item] || analytics?.equity_graph?.[item.toLowerCase()]
  );
  const portfolioAllocationEntries = Object.entries(analytics?.portfolio_allocations || {}).map(
    ([allocationId, allocation]) => ({
      portfolioId: allocationId,
      name: allocation?.portfolio_name || "Unnamed Baskt",
      type: formatAllocationType(allocation?.allocation_type),
      rawType: String(allocation?.allocation_type || ""),
      equity: Number(allocation?.allocation_equity || 0),
      percentOfAccount: Number(allocation?.allocation_equity_percent || 0),
      oneDayReturn: allocationReturns[allocationId],
    })
  );
  const stockAllocationEntries = Object.entries(analytics?.stock_allocations || {}).map(
    ([allocationId, allocation]) => ({
      portfolioId: allocationId,
      name: allocation?.stock_symbol || "Unnamed stock",
      type: formatAllocationType(allocation?.allocation_type),
      rawType: String(allocation?.allocation_type || ""),
      direction: formatDirection(allocation?.direction),
      equity: Number(allocation?.allocation_equity || 0),
      percentOfAccount: Number(allocation?.allocation_equity_percent || 0),
      oneDayReturn: allocationReturns[allocationId],
    })
  );
  const allocationEntries = [
    ...portfolioAllocationEntries,
    ...stockAllocationEntries,
  ];
  const selectedEquity = (selectedGraph?.equity || [])
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map(Number)
    .filter(Number.isFinite);
  const hasSelectedPeriodPnl = selectedEquity.length >= 2 && selectedEquity[0] !== 0;
  const selectedPeriodPnl = hasSelectedPeriodPnl
    ? selectedEquity.at(-1) - selectedEquity[0]
    : null;
  const selectedPeriodPnlPercent = hasSelectedPeriodPnl
    ? (selectedPeriodPnl / Math.abs(selectedEquity[0])) * 100
    : null;
  const selectedPeriodTone = selectedPeriodPnl > 0 ? "positive" : selectedPeriodPnl < 0 ? "negative" : "neutral";
  const selectedPeriodMoveLabel = periodMoveLabels[String(period).toUpperCase()] || period;

  return (
    <div className="page-stack dashboard-page">
      <ErrorBanner message={error} />
      <div className="dashboard-grid">
        <section className="portfolio-console">
          <div className="portfolio-heading">
            <div>
              <h1>{isLoading ? "—" : currency(analytics?.equity)}</h1>
              <p className={`portfolio-move ${selectedPeriodTone}`}>
                <strong>{isLoading ? "Loading" : signedCurrency(selectedPeriodPnl)}</strong>
                <span>{Number.isFinite(selectedPeriodPnlPercent) ? `${selectedPeriodPnlPercent > 0 ? "+" : ""}${percent(selectedPeriodPnlPercent)} ${selectedPeriodMoveLabel}` : "Not available"}</span>
              </p>
            </div>
          </div>

          <div className="dashboard-chart">
            {isLoading ? (
              <LoadingState title="Loading equity graph" message="Fetching account history." />
            ) : (
              <EquityChart equity={selectedGraph?.equity || []} timestamps={selectedGraph?.timestamp || []} valueType="currency" variant="wide" align="left" />
            )}
          </div>

          <div className="chart-periods segmented-control">
            {(availablePeriods.length ? availablePeriods : periods).map((item) => (
              <button key={item} className={period === item ? "active" : ""} type="button" onClick={() => setPeriod(item)}>{item}</button>
            ))}
          </div>

          <div className="buying-power-row">
            <span>Buying power</span>
            <strong>{isLoading ? "—" : currency(analytics?.cash)}</strong>
          </div>
        </section>

        <aside className="holdings-panel">
          <div className="holdings-heading">
            <div><h2>Holdings</h2></div>
            <span>{allocationEntries.length}</span>
          </div>

        {isLoading ? (
          <LoadingState title="Loading investments" message="Fetching your Baskts and stocks." />
        ) : allocationEntries.length ? (
          <div className="holdings-list">
            {allocationEntries.map((allocation) => (
              <button className="holding-row" key={allocation.portfolioId} type="button" onClick={() => onOpenInvestment?.(allocation)}>
                <span className="holding-name">
                  <strong>{allocation.name}</strong>
                  <small>
                    {allocation.type}
                    {allocation.direction ? (
                      <span className={`holding-direction ${allocation.direction.toLowerCase()}`}>
                        {allocation.direction}
                      </span>
                    ) : null}
                  </small>
                </span>
                <span className="holding-metrics">
                  <span className="holding-value">
                    <strong>{currency(allocation.equity)}</strong>
                    <small>{percent(allocation.percentOfAccount * 100)} of account</small>
                  </span>
                  <span
                    className={`holding-return ${getReturnTone(allocation.oneDayReturn)}`}
                    title="1D cumulative return is the total percentage return for this stock or Baskt over the current one-day analytics period."
                  >
                    <small>1D return</small>
                    <strong>{formatReturnChip(allocation.oneDayReturn)}</strong>
                  </span>
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-panel compact-empty">
            <h3>No invested allocations yet</h3>
            <p>Your invested Baskts and stocks will appear here after your first trade fills.</p>
          </div>
        )}
        </aside>
      </div>
    </div>
  );
}
