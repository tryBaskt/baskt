import { useEffect, useState } from "react";
import EquityChart from "../components/EquityChart";
import MetricCard from "../components/MetricCard";
import { ErrorBanner, LoadingState } from "../components/Status";
import { apiRequest } from "../lib/api";
import { currency } from "../lib/format";

const periods = ["1D", "1W", "1M", "3M", "1A", "ALL"];

export default function HomePage() {
  const [analytics, setAnalytics] = useState(null);
  const [period, setPeriod] = useState("1M");
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

  if (isLoading) {
    return <LoadingState title="Loading account" message="Pulling your buying power and equity history." />;
  }

  const selectedGraph = analytics?.equity_graph?.[period] || analytics?.equity_graph?.[period.toLowerCase()];
  const availablePeriods = periods.filter(
    (item) => analytics?.equity_graph?.[item] || analytics?.equity_graph?.[item.toLowerCase()]
  );

  return (
    <div className="page-stack">
      <ErrorBanner message={error} />
      <section className="hero-band purple">
        <div>
          <p className="eyebrow">Account analytics</p>
          <h2>Your money, positions, and momentum in one place.</h2>
        </div>
        <div className="metric-grid compact">
          <MetricCard label="Buying power" value={currency(analytics?.cash)} detail="Available cash" />
          <MetricCard label="Equity value" value={currency(analytics?.equity)} detail="Current account value" />
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
        <EquityChart equity={selectedGraph?.equity || []} />
      </section>
    </div>
  );
}
