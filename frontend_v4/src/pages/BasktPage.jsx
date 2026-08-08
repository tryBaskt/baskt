import { useEffect, useMemo, useState } from "react";
import EquityChart from "../components/EquityChart";
import MetricCell, { METRIC_EXPLANATIONS } from "../components/MetricCell";
import PositionsTable from "../components/PositionsTable";
import { EmptyState, ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest } from "../lib/api";
import { currency, formatDate, formatDateTime, formatMetricNumber, percent } from "../lib/format";
import { getCurrentUserClaims } from "../lib/session";
import { sortTransactionsNewestFirst } from "../lib/transactions";

function getReturnTone(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "";
  }
  return Number(value) >= 0 ? "metric-positive" : "metric-negative";
}

export default function BasktPage({ portfolioId, onBack, onUpdate, onOpenUser }) {
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
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [accesses, setAccesses] = useState([]);
  const [shareEmail, setShareEmail] = useState("");
  const [shareError, setShareError] = useState("");
  const [isBasktLoading, setIsBasktLoading] = useState(true);
  const [isAllocationLoading, setIsAllocationLoading] = useState(true);
  const [isModelAnalyticsLoading, setIsModelAnalyticsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAccessLoading, setIsAccessLoading] = useState(false);
  const [isAccessSubmitting, setIsAccessSubmitting] = useState(false);
  const [removingAccessId, setRemovingAccessId] = useState("");

  const claims = useMemo(() => getCurrentUserClaims(), []);
  const isOwner = claims?.sub && baskt?.portfolio_owner_cognito_user_id === claims.sub;
  const latestSnapshot = baskt?.position_history?.at(-1);
  const modelAnalyticsPeriods = ["1D", "1W", "1M", "3M", "1A", "all"];
  const selectedModelAnalytics =
    modelAnalytics?.[modelAnalyticsPeriod] ||
    modelAnalytics?.[modelAnalyticsPeriod.toLowerCase()];
  const selectedCumulativeReturns = selectedModelAnalytics?.cumulative_returns || [];
  const sortedTransactions = useMemo(
    () => sortTransactionsNewestFirst(transactions),
    [transactions]
  );
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

  async function loadAllocationAnalytics(signal) {
    setIsAllocationLoading(true);
    setAllocationError("");
    try {
      const allocationPayload = await apiRequest(
        `/allocation_analytics/portfolios/${portfolioId}/analytics`,
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

  async function loadAccesses(signal) {
    if (!portfolioId || !isOwner) return;
    setIsAccessLoading(true);
    setShareError("");
    try {
      const accessPayload = await apiRequest(
        `/model-portfolios/${portfolioId}/accesses`,
        { signal }
      );
      setAccesses(Array.isArray(accessPayload) ? accessPayload : []);
    } catch (accessError) {
      if (accessError?.name !== "AbortError") {
        setShareError(accessError?.message || "Could not load shared access.");
      }
    } finally {
      if (!signal?.aborted) {
        setIsAccessLoading(false);
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
        void loadAllocationAnalytics(controller.signal);
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
    setIsShareOpen(false);
    setAccesses([]);
    setShareEmail("");
    setShareError("");
    setIsAllocationLoading(true);
    void loadBasktDetails();
    void loadModelAnalytics(controller.signal);

    return () => {
      controller.abort();
    };
  }, [portfolioId]);

  useEffect(() => {
    if (!isShareOpen || !isOwner) return undefined;
    const controller = new AbortController();
    void loadAccesses(controller.signal);
    return () => {
      controller.abort();
    };
  }, [isShareOpen, isOwner, portfolioId]);

  async function addAccess(event) {
    event.preventDefault();
    const normalizedEmail = shareEmail.trim();
    if (!normalizedEmail) {
      setShareError("Enter an email address.");
      return;
    }

    setShareError("");
    setSuccess("");
    try {
      setIsAccessSubmitting(true);
      await apiRequest(`/model-portfolios/${portfolioId}/accesses`, {
        method: "POST",
        body: JSON.stringify({ email_address: normalizedEmail }),
      });
      setShareEmail("");
      setSuccess("Access shared.");
      await loadAccesses();
    } catch (accessError) {
      setShareError(accessError?.message || "Could not share access.");
    } finally {
      setIsAccessSubmitting(false);
    }
  }

  async function removeAccess(cognitoUserId) {
    setShareError("");
    setSuccess("");
    try {
      setRemovingAccessId(cognitoUserId);
      await apiRequest(`/model-portfolios/${portfolioId}/accesses`, {
        method: "DELETE",
        body: JSON.stringify({ cognito_user_id: cognitoUserId }),
      });
      setSuccess("Access removed.");
      await loadAccesses();
    } catch (accessError) {
      setShareError(accessError?.message || "Could not remove access.");
    } finally {
      setRemovingAccessId("");
    }
  }

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
      const requestOptions = {
        method: "POST",
      };
      if (needsAmount) {
        requestOptions.body = JSON.stringify({ amount: Number(amount) });
      }
      await apiRequest(`/trade-execution/portfolios/${portfolioId}/${endpoint}`, requestOptions);
      setSuccess(`${action === "withdraw-all" ? "Withdraw all" : action} request submitted.`);
      setAmount("");
      await loadAllocationAnalytics();
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
    <div className="page-stack investment-detail-page">
      <div className="detail-header">
        <button className="ghost-button" type="button" onClick={onBack}>Back</button>
        {isOwner ? (
          <>
            <button className="ghost-button" type="button" onClick={() => setIsShareOpen((current) => !current)}>Share</button>
            <button className="primary-button" type="button" onClick={onUpdate}>Update</button>
          </>
        ) : null}
      </div>
      <ErrorBanner message={error} />
      <SuccessBanner message={success} />
      <ErrorBanner message={allocationError} />

      <div className="investment-console-grid">
        <main className="investment-main">
          <section className="investment-hero">
            <div>
              <div className="baskt-title-row">
                <h1>{baskt.portfolio_name}</h1>
                {baskt.portfolio_owner_display_name ? (
                  <button
                    className="baskt-owner-name"
                    type="button"
                    onClick={() => onOpenUser(baskt.portfolio_owner_cognito_user_id)}
                  >
                    By {baskt.portfolio_owner_display_name}
                  </button>
                ) : null}
              </div>
              <p>{baskt.description || "No description yet."}</p>
            </div>
            <div className="investment-hero-meta">
              <span>Created <strong>{formatDate(baskt.created_at)}</strong></span>
              <span>Updated <strong>{formatDate(baskt.updated_at)}</strong></span>
              <span>Snapshots <strong>{baskt.position_history?.length || 0}</strong></span>
              <span>Visibility <strong className={baskt.visibility === "PRIVATE" ? "visibility-value private" : "visibility-value public"}>{baskt.visibility === "PRIVATE" ? "Private" : "Public"}</strong></span>
            </div>
          </section>

          <section className="investment-performance-console">
            <div className="investment-console-heading">
              <div>
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
              <div className="investment-performance-grid">
                <EquityChart
                  equity={selectedCumulativeReturns}
                  timestamps={selectedModelAnalytics?.timestamp || []}
                  valueType="percent"
                  variant="performance"
                  align="left"
                  ariaLabel={`${modelAnalyticsPeriod} model portfolio cumulative returns chart`}
                  emptyMessage="Model portfolio returns will appear here once price bars are available."
                />

                <div className="model-performance-metrics" aria-label={`${modelAnalyticsPeriod} performance metrics`}>
                  <MetricCell description={METRIC_EXPLANATIONS.return}>
                    <span>Cumulative return</span>
                    <strong className={getReturnTone(selectedPeriodCumulativeReturn)}>
                      {Number.isFinite(selectedPeriodCumulativeReturn)
                        ? percent(selectedPeriodCumulativeReturn)
                        : "Not available"}
                    </strong>
                    <small>{modelAnalyticsPeriod === "all" ? "All time" : modelAnalyticsPeriod}</small>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.cagr}>
                    <span>CAGR</span>
                    <strong className={getReturnTone(selectedModelAnalytics?.cagr)}>
                      {selectedModelAnalytics?.cagr !== null && selectedModelAnalytics?.cagr !== undefined
                        ? percent(Number(selectedModelAnalytics.cagr) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.volatility}>
                    <span>Annualized volatility</span>
                    <strong className="metric-accent">
                      {selectedModelAnalytics?.annualized_volatility !== null && selectedModelAnalytics?.annualized_volatility !== undefined
                        ? percent(Number(selectedModelAnalytics.annualized_volatility) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.direction}>
                    <span>Leverage-adjusted direction tilt</span>
                    <strong className="metric-accent">
                      {selectedModelAnalytics?.leverage_adjusted_direction !== null && selectedModelAnalytics?.leverage_adjusted_direction !== undefined
                        ? percent(Number(selectedModelAnalytics.leverage_adjusted_direction) * 100)
                        : "Not available"}
                    </strong>
                    <small>Long + / short -</small>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.alpha}>
                    <span>Alpha</span>
                    <strong className={getReturnTone(selectedModelAnalytics?.alpha)}>
                      {selectedModelAnalytics?.alpha !== null && selectedModelAnalytics?.alpha !== undefined
                        ? percent(Number(selectedModelAnalytics.alpha) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.beta}>
                    <span>Beta</span>
                    <strong className="metric-accent">
                      {selectedModelAnalytics?.beta !== null && selectedModelAnalytics?.beta !== undefined
                        ? formatMetricNumber(selectedModelAnalytics.beta)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.sharpe}>
                    <span>Sharpe ratio</span>
                    <strong className="metric-accent">
                      {selectedModelAnalytics?.sharpe_ratio !== null && selectedModelAnalytics?.sharpe_ratio !== undefined
                        ? formatMetricNumber(selectedModelAnalytics.sharpe_ratio)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.drawdown}>
                    <span>Maximum drawdown</span>
                    <strong className={getReturnTone(selectedModelAnalytics?.maximum_drawdown)}>
                      {selectedModelAnalytics?.maximum_drawdown !== null && selectedModelAnalytics?.maximum_drawdown !== undefined
                        ? percent(Number(selectedModelAnalytics.maximum_drawdown) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.drawdownDuration}>
                    <span>Maximum drawdown duration</span>
                    <strong className="metric-accent">
                      {selectedModelAnalytics?.maximum_drawdown_duration !== null && selectedModelAnalytics?.maximum_drawdown_duration !== undefined
                        ? formatMetricNumber(selectedModelAnalytics.maximum_drawdown_duration, { suffix: " days" })
                        : "Not available"}
                    </strong>
                  </MetricCell>
                </div>
              </div>
            )}
          </section>

          <section className="panel investment-panel">
            <div className="section-heading">
              <div>
                <h2>Current positions</h2>
              </div>
            </div>
            <PositionsTable positions={latestSnapshot?.positions || []} currentWeights={baskt.positions_current_weight} />
          </section>

          <section className="panel investment-panel">
            <div className="section-heading">
              <div>
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
        </main>

        <aside className="investment-rail">
          {isOwner && isShareOpen ? (
            <section className="rail-panel share-access-panel">
              <div className="section-heading compact-heading">
                <div>
                  <h2>Share access</h2>
                </div>
              </div>
              <form className="share-access-form" onSubmit={addAccess}>
                <label className="field">
                  <span>Email address</span>
                  <input
                    type="email"
                    value={shareEmail}
                    onChange={(event) => setShareEmail(event.target.value)}
                    placeholder="member@example.com"
                    autoComplete="email"
                  />
                </label>
                <button className="primary-button" type="submit" disabled={isAccessSubmitting || !shareEmail.trim()}>
                  {isAccessSubmitting ? "Sharing..." : "Add access"}
                </button>
              </form>
              {shareError ? <ErrorBanner message={shareError} /> : null}
              <div className="share-access-list" aria-live="polite">
                {isAccessLoading ? (
                  <p className="muted">Loading access...</p>
                ) : accesses.length ? (
                  accesses.map((access) => (
                    <div className="share-access-row" key={access.cognito_user_id}>
                      <span>{access.email_address}</span>
                      <button
                        className="danger-button"
                        type="button"
                        disabled={removingAccessId === access.cognito_user_id}
                        onClick={() => removeAccess(access.cognito_user_id)}
                      >
                        {removingAccessId === access.cognito_user_id ? "Removing..." : "Remove"}
                      </button>
                    </div>
                  ))
                ) : (
                  <p className="muted">No shared access yet.</p>
                )}
              </div>
            </section>
          ) : null}

          <section className="rail-panel">
            {isAllocationLoading ? (
              <strong>Loading...</strong>
            ) : hasAllocationMetrics ? (
              <div className="rail-metric-stack">
                <div>
                  <span>Allocation equity</span>
                  <strong>{currency(allocationAnalytics?.equity, "Not available")}</strong>
                  <small>Basis {currency(allocationAnalytics?.total_cost_basis, "Not available")}</small>
                </div>
                <div>
                  <span>Profit/Loss</span>
                  <strong className={getReturnTone(allocationAnalytics?.profit_loss)}>
                    {currency(allocationAnalytics?.profit_loss, "Not available")}
                  </strong>
                </div>
                <div>
                  <span>Profit/Loss %</span>
                  <strong className={getReturnTone(allocationAnalytics?.profit_loss_percent)}>
                    {percent(Number(allocationAnalytics.profit_loss_percent) * 100)}
                  </strong>
                </div>
              </div>
            ) : (
              <p className="muted">No funded allocation yet.</p>
            )}
          </section>

          <section className="rail-panel trade-action-panel">
            <div className="section-heading compact-heading">
              <div>
                <h2>Deposit or Withdraw</h2>
              </div>
            </div>
            <label className="field">
              <span>Amount</span>
              <input type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} />
            </label>
            <div className="rail-button-stack">
              <button className="primary-button" type="button" disabled={isSubmitting} onClick={() => executeTrade("deposit")}>Deposit</button>
              <button className="ghost-button" type="button" disabled={isSubmitting} onClick={() => executeTrade("withdraw")}>Withdraw</button>
              <button className="danger-button" type="button" disabled={isSubmitting} onClick={() => executeTrade("withdraw-all")}>Withdraw all</button>
            </div>
          </section>

          <section className="rail-panel">
            <div className="section-heading compact-heading">
              <div>
                <h2>Recent activity</h2>
              </div>
            </div>
            {isAllocationLoading ? (
              <p className="muted" aria-live="polite">Loading transactions...</p>
            ) : (
              <div className="rail-activity-list">
                {sortedTransactions.slice(0, 5).map((transaction) => (
                  <div key={transaction.transaction_id} className="rail-activity-row">
                    <span>
                      <strong>{transaction.transaction_type}</strong>
                      <small>{formatDateTime(transaction.created_at)}</small>
                    </span>
                    <span>
                      <strong>{currency(transaction.cost_basis, "Not available")}</strong>
                      <small>Requested {currency(transaction.requested_amount, "Not available")}</small>
                      <small>{transaction.status}</small>
                    </span>
                  </div>
                ))}
                {!transactions.length && !allocationError ? <p className="muted">No transactions yet.</p> : null}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
