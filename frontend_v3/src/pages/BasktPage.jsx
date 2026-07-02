import { useEffect, useMemo, useState } from "react";
import EquityChart from "../components/EquityChart";
import PositionsTable from "../components/PositionsTable";
import { EmptyState, ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { currency, formatDate, formatDateTime, percent } from "../lib/format";
import { getCurrentUserClaims } from "../lib/session";

function getReturnTone(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "";
  }
  return Number(value) >= 0 ? "metric-positive" : "metric-negative";
}

export default function BasktPage({ portfolioId, onBack, onUpdate }) {
  const [baskt, setBaskt] = useState(null);
  const [allocationAnalytics, setAllocationAnalytics] = useState(null);
  const [modelAnalytics, setModelAnalytics] = useState(null);
  const [modelAnalyticsPeriod, setModelAnalyticsPeriod] = useState("1D");
  const [transactions, setTransactions] = useState([]);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [allocationError, setAllocationError] = useState("");
  const [modelAnalyticsError, setModelAnalyticsError] = useState("");
  const [success, setSuccess] = useState("");
  const [isBasktLoading, setIsBasktLoading] = useState(true);
  const [isAllocationLoading, setIsAllocationLoading] = useState(true);
  const [isModelAnalyticsLoading, setIsModelAnalyticsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const claims = useMemo(() => getCurrentUserClaims(), []);
  const isOwner = claims?.sub && baskt?.portfolio_owner_cognito_user_id === claims.sub;
  const latestSnapshot = baskt?.position_history?.at(-1);
  const modelAnalyticsPeriods = ["1D", "1W", "1M", "3M", "1A", "all"];
  const selectedModelAnalytics =
    modelAnalytics?.[modelAnalyticsPeriod] ||
    modelAnalytics?.[modelAnalyticsPeriod.toLowerCase()];
  const selectedCumulativeReturns = selectedModelAnalytics?.cumulative_returns || [];
  const selectedPeriodCumulativeReturn =
    selectedModelAnalytics?.final_cumulative_return !== null &&
    selectedModelAnalytics?.final_cumulative_return !== undefined
      ? Number(selectedModelAnalytics.final_cumulative_return) * 100
      : null;
  const hasAllocationMetrics =
    allocationAnalytics?.equity !== null &&
    allocationAnalytics?.equity !== undefined &&
    allocationAnalytics?.profit_loss !== null &&
    allocationAnalytics?.profit_loss !== undefined &&
    allocationAnalytics?.profit_loss_percent !== null &&
    allocationAnalytics?.profit_loss_percent !== undefined;

  async function loadAllocationAnalytics(ownerCognitoUserId, signal) {
    setIsAllocationLoading(true);
    setAllocationError("");
    const query = toQuery({
      portfolio_owner_cognito_user_id: ownerCognitoUserId,
    });
    try {
      const allocationPayload = await apiRequest(
        `/account-analytics/portfolios/${portfolioId}/analytics${query}`,
        { signal }
      );
      setAllocationAnalytics(allocationPayload || null);
      setTransactions(allocationPayload?.transaction_history || []);
    } catch (allocationRequestError) {
      if (allocationRequestError?.name !== "AbortError") {
        setAllocationError(
          allocationRequestError?.message || "Could not load allocation analytics."
        );
      }
    } finally {
      if (!signal?.aborted) {
        setIsAllocationLoading(false);
      }
    }
  }

  async function loadModelAnalytics(signal) {
    setIsModelAnalyticsLoading(true);
    setModelAnalyticsError("");
    try {
      const modelAnalyticsPayload = await apiRequest(
        `/model-portfolios/${portfolioId}/analytics`,
        { signal }
      );
      setModelAnalytics(modelAnalyticsPayload || null);
      if (!modelAnalyticsPayload?.[modelAnalyticsPeriod]) {
        const availablePeriod = modelAnalyticsPeriods.find(
          (period) => modelAnalyticsPayload?.[period]
        );
        if (availablePeriod) {
          setModelAnalyticsPeriod(availablePeriod);
        }
      }
    } catch (modelAnalyticsRequestError) {
      if (modelAnalyticsRequestError?.name !== "AbortError") {
        setModelAnalyticsError(
          modelAnalyticsRequestError?.message || "Could not load model performance."
        );
      }
    } finally {
      if (!signal?.aborted) {
        setIsModelAnalyticsLoading(false);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();

    async function loadBasktDetails() {
      try {
        setIsBasktLoading(true);
        setError("");
        setBaskt(null);
        setAllocationAnalytics(null);
        setTransactions([]);
        const payload = await apiRequest(`/model-portfolios/${portfolioId}`, {
          signal: controller.signal,
        });
        setBaskt(payload);
        void loadAllocationAnalytics(
          payload.portfolio_owner_cognito_user_id,
          controller.signal
        );
      } catch (basktError) {
        if (basktError?.name !== "AbortError") {
          setError(basktError?.message || "Could not load this Baskt.");
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsBasktLoading(false);
        }
      }
    }

    setModelAnalytics(null);
    setIsAllocationLoading(true);
    void loadBasktDetails();
    void loadModelAnalytics(controller.signal);

    return () => {
      controller.abort();
    };
  }, [portfolioId]);

  async function executeTrade(action) {
    setError("");
    setSuccess("");

    const needsAmount = action !== "withdraw-all";
    if (needsAmount && Number(amount) <= 0) {
      setError("Enter an amount greater than zero.");
      return;
    }

    const endpoint =
      action === "deposit"
        ? "deposit"
        : action === "withdraw-all"
          ? "withdraw-all"
          : "withdrawal";

    try {
      setIsSubmitting(true);
      await apiRequest(`/trade-execution/portfolios/${portfolioId}/${endpoint}`, {
        method: "POST",
        body: JSON.stringify({
          portfolio_owner_cognito_user_id: baskt.portfolio_owner_cognito_user_id,
          ...(needsAmount ? { amount: Number(amount) } : {}),
        }),
      });
      setSuccess(`${action === "withdraw-all" ? "Withdraw all" : action} request submitted.`);
      setAmount("");
      await loadAllocationAnalytics(baskt.portfolio_owner_cognito_user_id);
    } catch (tradeError) {
      setError(tradeError?.message || "Trade request failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isBasktLoading) {
    return <LoadingState title="Loading Baskt" message="Fetching portfolio details." />;
  }

  if (!baskt) {
    return <EmptyState title="Baskt unavailable" message="This portfolio could not be found." />;
  }

  return (
    <div className="page-stack">
      <div className="detail-header">
        <button className="ghost-button" type="button" onClick={onBack}>Back</button>
        {isOwner ? <button className="primary-button" type="button" onClick={onUpdate}>Update</button> : null}
      </div>
      <ErrorBanner message={error} />
      <SuccessBanner message={success} />

      <section className="hero-band">
        <div>
          <p className="eyebrow">Baskt detail</p>
          <h2>{baskt.portfolio_name}</h2>
          <p>{baskt.description || "No description yet."}</p>
        </div>
        <div className="meta-grid">
          <span>Created <strong>{formatDate(baskt.created_at)}</strong></span>
          <span>Updated <strong>{formatDate(baskt.updated_at)}</strong></span>
          <span>Snapshots <strong>{baskt.position_history?.length || 0}</strong></span>
        </div>
      </section>

      <ErrorBanner message={allocationError} />

      {isAllocationLoading ? (
        <section className="analytics-bar" aria-live="polite" aria-busy="true">
          <div>
            <span>Allocation analytics</span>
            <strong>Loading...</strong>
            <small>Fetching current value and activity</small>
          </div>
        </section>
      ) : hasAllocationMetrics ? (
        <section className="analytics-bar" aria-label="Baskt allocation analytics">
          <div>
            <span>Allocation equity</span>
            <strong>{currency(allocationAnalytics?.equity, "Not available")}</strong>
            <small>Basis {currency(allocationAnalytics?.total_cost_basis, "Not available")}</small>
          </div>
          <div>
            <span>Profit/Loss</span>
            <strong>{currency(allocationAnalytics?.profit_loss, "Not available")}</strong>
            <small>Current value minus basis</small>
          </div>
          <div>
            <span>Profit/Loss %</span>
            <strong>{percent(Number(allocationAnalytics.profit_loss_percent) * 100)}</strong>
            <small>Return on allocated basis</small>
          </div>
        </section>
      ) : null}

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Model performance</p>
            <h2>Cumulative returns</h2>
          </div>
          <div className="segmented-control" aria-label="Model portfolio analytics period">
            {modelAnalyticsPeriods.map((period) => (
              <button
                key={period}
                className={modelAnalyticsPeriod === period ? "active" : ""}
                type="button"
                onClick={() => setModelAnalyticsPeriod(period)}
              >
                {period}
              </button>
            ))}
          </div>
        </div>

        {isModelAnalyticsLoading ? (
          <p className="muted" aria-live="polite">Loading model performance...</p>
        ) : modelAnalyticsError ? (
          <ErrorBanner message={modelAnalyticsError} />
        ) : (
          <div className="model-performance-layout">
            <EquityChart
              equity={selectedCumulativeReturns}
              timestamps={selectedModelAnalytics?.timestamp || []}
              valueType="percent"
              variant="wide"
              align="left"
              ariaLabel={`${modelAnalyticsPeriod} model portfolio cumulative returns chart`}
              emptyMessage="Model portfolio returns will appear here once price bars are available."
            />

            <div className="model-performance-metrics" aria-label={`${modelAnalyticsPeriod} performance metrics`}>
              <div>
                <span>Cumulative return</span>
                <strong className={getReturnTone(selectedPeriodCumulativeReturn)}>
                  {Number.isFinite(selectedPeriodCumulativeReturn)
                    ? percent(selectedPeriodCumulativeReturn)
                    : "Not available"}
                </strong>
                <small>{modelAnalyticsPeriod === "all" ? "All time" : modelAnalyticsPeriod}</small>
              </div>
              <div>
                <span>CAGR</span>
                <strong className={getReturnTone(selectedModelAnalytics?.cagr)}>
                  {selectedModelAnalytics?.cagr !== null && selectedModelAnalytics?.cagr !== undefined
                    ? percent(Number(selectedModelAnalytics.cagr) * 100)
                    : "Not available"}
                </strong>
              </div>
              <div>
                <span>Annualized volatility</span>
                <strong className="metric-accent">
                  {selectedModelAnalytics?.annualized_volatility !== null && selectedModelAnalytics?.annualized_volatility !== undefined
                    ? percent(Number(selectedModelAnalytics.annualized_volatility) * 100)
                    : "Not available"}
                </strong>
              </div>
              <div>
                <span>Leverage-adjusted direction tilt</span>
                <strong className="metric-accent">
                  {selectedModelAnalytics?.leverage_adjusted_direction !== null && selectedModelAnalytics?.leverage_adjusted_direction !== undefined
                    ? percent(Number(selectedModelAnalytics.leverage_adjusted_direction) * 100)
                    : "Not available"}
                </strong>
                <small>Long + / short -</small>
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Latest allocation</p>
            <h2>Current positions</h2>
          </div>
        </div>
        <PositionsTable positions={latestSnapshot?.positions || []} currentWeights={baskt.positions_current_weight} />
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Position history</p>
            <h2>Previous snapshots</h2>
          </div>
        </div>
        <div className="snapshot-list">
          {(baskt.position_history || []).slice(0, -1).reverse().map((snapshot) => (
            <details key={snapshot.timestamp}>
              <summary>{formatDateTime(snapshot.timestamp)}</summary>
              <PositionsTable positions={snapshot.positions} />
            </details>
          ))}
          {(baskt.position_history || []).length <= 1 ? <p className="muted">No previous snapshots yet.</p> : null}
        </div>
      </section>

      <section className="split-grid">
        <div className="panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Funding this Baskt</p>
              <h2>Deposit or withdraw</h2>
            </div>
          </div>
          <label className="field">
            <span>Amount</span>
            <input type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} />
          </label>
          <div className="button-row">
            <button className="primary-button" type="button" disabled={isSubmitting} onClick={() => executeTrade("deposit")}>Deposit</button>
            <button className="ghost-button" type="button" disabled={isSubmitting} onClick={() => executeTrade("withdraw")}>Withdraw</button>
            <button className="danger-button" type="button" disabled={isSubmitting} onClick={() => executeTrade("withdraw-all")}>Withdraw all</button>
          </div>
        </div>

        <div className="panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Transactions</p>
              <h2>Portfolio activity</h2>
            </div>
          </div>
          {isAllocationLoading ? (
            <p className="muted" aria-live="polite">Loading transactions...</p>
          ) : (
            <div className="table-wrap compact-table">
            <table className="transactions-table">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Filled at</th>
                  <th>Type</th>
                  <th>Requested</th>
                  <th>Filled amount</th>
                  <th>Fill percent</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((transaction) => (
                  <tr key={transaction.transaction_id}>
                    <td>{formatDateTime(transaction.created_at)}</td>
                    <td>{formatDateTime(transaction.filled_at)}</td>
                    <td>{transaction.transaction_type}</td>
                    <td>
                      {transaction.requested_amount === null || transaction.requested_amount === undefined
                        ? "Withdraw all"
                        : currency(transaction.requested_amount)}
                    </td>
                    <td>{currency(transaction.cost_basis)}</td>
                    <td>{percent(transaction.order_fill_percent)}</td>
                    <td>{transaction.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
              {!transactions.length && !allocationError ? <p className="muted">No transactions yet.</p> : null}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
