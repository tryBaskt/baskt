import { useEffect, useState } from "react";
import EquityChart from "../components/EquityChart";
import MetricCard from "../components/MetricCard";
import { ErrorBanner, LoadingState } from "../components/Status";
import { apiRequest } from "../lib/api";
import { currency, percent } from "../lib/format";

const periods = ["1D", "1W", "1M", "3M", "1A", "ALL"];

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

export default function HomePage({ onOpenInvestment }) {
  const [analytics, setAnalytics] = useState(null);
  const [period, setPeriod] = useState("1D");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let ignore = false;

    async function loadAnalytics() {
      try {
        setIsLoading(true);
        const payload = await apiRequest("/account-analytics");
        if (!ignore) {
          setAnalytics(payload);
          const availablePeriods = Object.keys(payload?.equity_graph || {});
          if (availablePeriods.length && !availablePeriods.includes(period)) {
            setPeriod(availablePeriods[0]);
          }
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
  const allocationEntries = Object.entries(analytics?.portfolio_allocations || {}).map(
    ([portfolioId, allocation]) => ({
      portfolioId,
      name: allocation?.portfolio_name || "Unnamed allocation",
      type: formatAllocationType(allocation?.portfolio_allocation_type),
      rawType: String(allocation?.portfolio_allocation_type || ""),
      equity: Number(allocation?.portfolio_allocation_equity || 0),
      percentOfAccount: Number(allocation?.portfolio_allocation_equity_percent || 0),
    })
  );
  const investedEquity = allocationEntries.reduce((total, allocation) => total + allocation.equity, 0);

  return (
    <div className="page-stack">
      <ErrorBanner message={error} />
      <section className="hero-band purple">
        <div className="metric-grid compact">
          <MetricCard
            label="Cash"
            value={isLoading ? "Loading..." : currency(analytics?.cash)}
            detail="Available cash"
          />
          <MetricCard
            label="Equity value"
            value={isLoading ? "Loading..." : currency(analytics?.equity)}
            detail="Current account value"
          />
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Equity graph</p>
            <h2>Performance over time</h2>
          </div>
          <div className="segmented-control">
            {(availablePeriods.length ? availablePeriods : periods).map((item) => (
              <button
                key={item}
                className={period === item ? "active" : ""}
                type="button"
                onClick={() => setPeriod(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        {isLoading ? (
          <LoadingState title="Loading equity graph" message="Fetching account history." />
        ) : (
          <EquityChart
            equity={selectedGraph?.equity || []}
            timestamps={selectedGraph?.timestamp || []}
            valueType="currency"
          />
        )}
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Invested allocations</p>
            <h2>Your Baskts and stocks</h2>
          </div>
          <div className="allocation-total">
            <span>Invested value</span>
            <strong>{isLoading ? "Loading..." : currency(investedEquity)}</strong>
          </div>
        </div>

        {isLoading ? (
          <LoadingState title="Loading investments" message="Fetching your Baskts and stocks." />
        ) : allocationEntries.length ? (
          <div className="home-allocation-list">
            <div className="home-allocation-scroll">
              <table className="home-allocation-table">
                <thead>
                  <tr>
                    <th>Investment</th>
                    <th>Type</th>
                    <th>Equity</th>
                    <th>Account weight</th>
                  </tr>
                </thead>
                <tbody>
                  {allocationEntries.map((allocation) => (
                    <tr
                      className="home-allocation-action"
                      key={allocation.portfolioId}
                      tabIndex={0}
                      onClick={() => onOpenInvestment?.(allocation)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onOpenInvestment?.(allocation);
                        }
                      }}
                    >
                      <td>
                        <strong>{allocation.name}</strong>
                      </td>
                      <td>
                        <span className={allocation.type === "Stock" ? "pill stock-pill" : "pill"}>
                          {allocation.type}
                        </span>
                      </td>
                      <td>
                        <strong>{currency(allocation.equity)}</strong>
                      </td>
                      <td>
                        <strong>{percent(allocation.percentOfAccount * 100)}</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div className="empty-panel compact-empty">
            <h3>No invested allocations yet</h3>
            <p>Your invested Baskts and stocks will appear here after your first trade fills.</p>
          </div>
        )}
      </section>
    </div>
  );
}
