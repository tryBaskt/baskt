import { useEffect, useMemo, useState } from "react";
import EquityChart from "../components/EquityChart";
import MetricCell, { METRIC_EXPLANATIONS } from "../components/MetricCell";
import { EmptyState, ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest } from "../lib/api";
import { currency, formatDateTime, formatMetricNumber, percent } from "../lib/format";
import { sortTransactionsNewestFirst } from "../lib/transactions";

const PERIODS = ["1D", "1W", "1M", "3M", "1A", "all"];

function getReturnTone(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "";
  }
  return Number(value) >= 0 ? "metric-positive" : "metric-negative";
}

export default function StockPage({ stockId, onBack }) {
  const [stock, setStock] = useState(null);
  const [stockAnalytics, setStockAnalytics] = useState(null);
  const [allocationAnalytics, setAllocationAnalytics] = useState(null);
  const [selectedPeriod, setSelectedPeriod] = useState("1D");
  const [amount, setAmount] = useState("");
  const [stockError, setStockError] = useState("");
  const [analyticsError, setAnalyticsError] = useState("");
  const [allocationError, setAllocationError] = useState("");
  const [tradeError, setTradeError] = useState("");
  const [success, setSuccess] = useState("");
  const [activeTradeTab, setActiveTradeTab] = useState("buy");
  const [isStockLoading, setIsStockLoading] = useState(true);
  const [isAnalyticsLoading, setIsAnalyticsLoading] = useState(true);
  const [isAllocationLoading, setIsAllocationLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const selectedAnalytics =
    stockAnalytics?.[selectedPeriod] || stockAnalytics?.[selectedPeriod.toLowerCase()];
  const prices = selectedAnalytics?.prices || [];
  const periodReturn =
    selectedAnalytics?.final_cumulative_return !== null &&
    selectedAnalytics?.final_cumulative_return !== undefined &&
    Number.isFinite(Number(selectedAnalytics.final_cumulative_return))
      ? Number(selectedAnalytics.final_cumulative_return) * 100
      : null;
  const transactions = useMemo(
    () => sortTransactionsNewestFirst(allocationAnalytics?.transaction_history || []),
    [allocationAnalytics?.transaction_history]
  );
  const hasAllocation =
    allocationAnalytics?.equity !== null &&
    allocationAnalytics?.equity !== undefined;
  const allocationDirection = Number(allocationAnalytics?.direction);
  const hasOpenPosition =
    hasAllocation &&
    Number.isFinite(allocationDirection) &&
    allocationDirection !== 0 &&
    Number(allocationAnalytics.equity) > 0;
  const sellLimit = hasOpenPosition ? Math.max(0, Number(allocationAnalytics.equity)) : 0;
  const allocationDirectionLabel = hasOpenPosition
    ? allocationDirection < 0
      ? "Short"
      : "Long"
    : "No open position";
  const secondaryTradeLabel = hasOpenPosition ? "Sell" : "Short";
  const isSecondaryTradeUnavailable =
    !stock?.tradable || (!hasOpenPosition && !stock?.shortable);
  const isSecondaryTradeDisabled = isSubmitting || isSecondaryTradeUnavailable;
  const capabilities = useMemo(
    () => [
      stock?.tradable ? "Tradable" : null,
      stock?.fractionable ? "Fractionable" : null,
      stock?.shortable ? "Shortable" : null,
      stock?.marginable ? "Marginable" : null,
    ].filter(Boolean),
    [stock]
  );

  async function loadStockDetails(signal) {
    setIsStockLoading(true);
    setStockError("");
    try {
      const payload = await apiRequest(
        `/stocks/${stockId}`,
        { signal }
      );
      setStock(payload || null);
      return payload || null;
    } catch (error) {
      if (error?.name !== "AbortError") {
        setStock(null);
        setStockError(error?.message || "Could not load stock details.");
      }
      return null;
    } finally {
      if (!signal?.aborted) {
        setIsStockLoading(false);
      }
    }
  }

  async function loadAllocationAnalytics(signal) {
    setIsAllocationLoading(true);
    setAllocationError("");
    try {
      const payload = await apiRequest(
        `/allocation_analytics/stocks/${stockId}/analytics`,
        { signal }
      );
      setAllocationAnalytics(payload || null);
    } catch (error) {
      if (error?.name !== "AbortError") {
        setAllocationError(error?.message || "Could not load your stock allocation.");
      }
    } finally {
      if (!signal?.aborted) {
        setIsAllocationLoading(false);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();

    setStockAnalytics(null);
    setAllocationAnalytics(null);
    setStock(null);
    setStockError("");
    setAnalyticsError("");
    setAllocationError("");
    setIsStockLoading(true);
    setIsAnalyticsLoading(true);
    setIsAllocationLoading(true);
    setActiveTradeTab("buy");

    void loadStockDetails(controller.signal).then((loadedStock) => {
      if (!loadedStock || controller.signal.aborted) {
        setIsAnalyticsLoading(false);
        setIsAllocationLoading(false);
        return;
      }

      void loadAllocationAnalytics(controller.signal);

      void apiRequest(`/stock-analytics/${encodeURIComponent(loadedStock.symbol)}`, {
        signal: controller.signal,
      })
        .then((payload) => {
          setStockAnalytics(payload || null);
          if (!payload?.[selectedPeriod]) {
            const availablePeriod = PERIODS.find((period) => payload?.[period]);
            if (availablePeriod) {
              setSelectedPeriod(availablePeriod);
            }
          }
        })
        .catch((error) => {
          if (error?.name !== "AbortError") {
            setAnalyticsError(error?.message || "Could not load stock performance.");
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) {
            setIsAnalyticsLoading(false);
          }
        });
    });

    return () => controller.abort();
  }, [stockId]);

  useEffect(() => {
    if (activeTradeTab === "sell" && isSecondaryTradeUnavailable) {
      setActiveTradeTab("buy");
    }
  }, [activeTradeTab, isSecondaryTradeUnavailable]);

  async function executeTrade(action) {
    setTradeError("");
    setSuccess("");

    const needsAmount = action !== "close";
    const numericAmount = Number(amount);
    if (needsAmount && (!Number.isFinite(numericAmount) || numericAmount <= 0)) {
      setTradeError("Enter an amount greater than zero.");
      return;
    }
    if (action === "sell" && !stock.shortable && numericAmount > sellLimit) {
      setTradeError(`Sell amount cannot exceed ${currency(sellLimit)}.`);
      return;
    }

    try {
      setIsSubmitting(true);
      const requestOptions = {
        method: "POST",
      };
      if (needsAmount) {
        requestOptions.body = JSON.stringify({ amount: numericAmount });
      }
      await apiRequest(`/trade-execution/stocks/${stock.stock_id}/${action}`, requestOptions);
      const actionLabel = action === "sell" && !hasOpenPosition ? "Short" : "Sell";
      setSuccess(
        action === "close"
          ? `Close request submitted for ${stock.symbol}.`
          : `${action === "buy" ? "Buy" : actionLabel} request submitted.`
      );
      setAmount("");
      await loadAllocationAnalytics();
    } catch (error) {
      setTradeError(error?.message || "Stock trade request failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isStockLoading) {
    return <LoadingState title="Loading stock" message="Fetching stock details." />;
  }

  if (!stock) {
    return (
      <div className="page-stack stock-detail-page">
        <div className="detail-header">
          <button className="ghost-button" type="button" onClick={onBack}>Back</button>
        </div>
        <ErrorBanner message={stockError} />
        <EmptyState title="Stock unavailable" message="This stock could not be found." />
      </div>
    );
  }

  return (
    <div className="page-stack stock-detail-page investment-detail-page">
      <div className="detail-header">
        <button className="ghost-button" type="button" onClick={onBack}>Back</button>
      </div>

      <ErrorBanner message={allocationError} />
      <ErrorBanner message={tradeError} />
      <SuccessBanner message={success} />

      <div className="investment-console-grid">
        <main className="investment-main">
          <section className="investment-hero stock-investment-hero">
            <div className="stock-identity">
              <div>
                <h1>{stock.symbol}</h1>
                <p>{String(stock.stock_class || "US equity").replaceAll("_", " ")}</p>
              </div>
            </div>
            <div className="stock-capabilities" aria-label="Stock capabilities">
              {capabilities.map((capability) => <span key={capability}>{capability}</span>)}
            </div>
          </section>

          <section className="investment-performance-console">
            <div className="investment-console-heading">
              <div>
                <h2>{stock.symbol} price history</h2>
              </div>
              <div className="segmented-control" aria-label="Stock analytics period">
                {PERIODS.map((period) => (
                  <button
                    key={period}
                    className={selectedPeriod === period ? "active" : ""}
                    type="button"
                    disabled={!stockAnalytics?.[period]}
                    onClick={() => setSelectedPeriod(period)}
                  >
                    {period}
                  </button>
                ))}
              </div>
            </div>

            {isAnalyticsLoading ? (
              <p className="muted" aria-live="polite">Loading stock performance...</p>
            ) : analyticsError ? (
              <ErrorBanner message={analyticsError} />
            ) : (
              <div className="investment-performance-grid">
                <EquityChart
                  equity={prices}
                  timestamps={selectedAnalytics?.timestamp || []}
                  valueType="currency"
                  variant="performance"
                  align="left"
                  ariaLabel={`${selectedPeriod} ${stock.symbol} price chart`}
                  emptyMessage="Stock prices are unavailable for this period."
                />
                <div className="model-performance-metrics" aria-label={`${selectedPeriod} stock metrics`}>
                  <MetricCell description={METRIC_EXPLANATIONS.return}>
                    <span>Cumulative return</span>
                    <strong className={getReturnTone(periodReturn)}>
                      {Number.isFinite(periodReturn) ? percent(periodReturn) : "Not available"}
                    </strong>
                    <small>{selectedPeriod === "all" ? "All time" : selectedPeriod}</small>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.cagr}>
                    <span>CAGR</span>
                    <strong className={getReturnTone(selectedAnalytics?.cagr)}>
                      {selectedAnalytics?.cagr !== null && selectedAnalytics?.cagr !== undefined
                        ? percent(Number(selectedAnalytics.cagr) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.volatility}>
                    <span>Annualized volatility</span>
                    <strong className="metric-accent">
                      {selectedAnalytics?.annualized_volatility !== null && selectedAnalytics?.annualized_volatility !== undefined
                        ? percent(Number(selectedAnalytics.annualized_volatility) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.direction}>
                    <span>Direction tilt</span>
                    <strong className="metric-accent">
                      {selectedAnalytics?.leverage_adjusted_direction !== null && selectedAnalytics?.leverage_adjusted_direction !== undefined
                        ? percent(Number(selectedAnalytics.leverage_adjusted_direction) * 100)
                        : "Not available"}
                    </strong>
                    <small>Long + / short -</small>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.alpha}>
                    <span>Alpha</span>
                    <strong className={getReturnTone(selectedAnalytics?.alpha)}>
                      {selectedAnalytics?.alpha !== null && selectedAnalytics?.alpha !== undefined
                        ? percent(Number(selectedAnalytics.alpha) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.beta}>
                    <span>Beta</span>
                    <strong className="metric-accent">
                      {selectedAnalytics?.beta !== null && selectedAnalytics?.beta !== undefined
                        ? formatMetricNumber(selectedAnalytics.beta)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.sharpe}>
                    <span>Sharpe ratio</span>
                    <strong className="metric-accent">
                      {selectedAnalytics?.sharpe_ratio !== null && selectedAnalytics?.sharpe_ratio !== undefined
                        ? formatMetricNumber(selectedAnalytics.sharpe_ratio)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.drawdown}>
                    <span>Maximum drawdown</span>
                    <strong className={getReturnTone(selectedAnalytics?.maximum_drawdown)}>
                      {selectedAnalytics?.maximum_drawdown !== null && selectedAnalytics?.maximum_drawdown !== undefined
                        ? percent(Number(selectedAnalytics.maximum_drawdown) * 100)
                        : "Not available"}
                    </strong>
                  </MetricCell>
                  <MetricCell description={METRIC_EXPLANATIONS.drawdownDuration}>
                    <span>Maximum drawdown duration</span>
                    <strong className="metric-accent">
                      {selectedAnalytics?.maximum_drawdown_duration !== null && selectedAnalytics?.maximum_drawdown_duration !== undefined
                        ? formatMetricNumber(selectedAnalytics.maximum_drawdown_duration, { suffix: " days" })
                        : "Not available"}
                    </strong>
                  </MetricCell>
                </div>
              </div>
            )}
          </section>
        </main>

        <aside className="investment-rail">
          <section className="rail-panel">
            {isAllocationLoading ? (
              <strong>Loading...</strong>
            ) : hasOpenPosition ? (
              <div className="rail-metric-stack">
                <div>
                  <span className="rail-metric-heading">
                    <span>Position value</span>
                    <strong className={allocationDirection < 0 ? "direction-badge short" : "direction-badge long"}>
                      {allocationDirectionLabel}
                    </strong>
                  </span>
                  <strong>{currency(allocationAnalytics.equity, "Not available")}</strong>
                  <small>Cost basis {currency(allocationAnalytics.total_cost_basis, "Not available")}</small>
                </div>
                <div>
                  <span>Profit/Loss</span>
                  <strong className={getReturnTone(allocationAnalytics.profit_loss)}>
                    {currency(allocationAnalytics.profit_loss, "Not available")}
                  </strong>
                </div>
                <div>
                  <span>Profit/Loss %</span>
                  <strong className={getReturnTone(allocationAnalytics.profit_loss_percent)}>
                    {percent(Number(allocationAnalytics.profit_loss_percent) * 100)}
                  </strong>
                </div>
              </div>
            ) : (
              <div className="rail-empty">
                <h2>You do not own {stock.symbol} yet</h2>
                <p>
                  {stock.shortable
                    ? "Enter an amount below to buy or open a short position."
                    : "Enter an amount below to place your first buy."}
                </p>
              </div>
            )}
          </section>

          <section className="rail-panel stock-trade-panel trade-action-panel">
            <div className="stock-trade-tabs" aria-label={`${stock.symbol} trade action`}>
              <button
                className={activeTradeTab === "buy" ? "active" : ""}
                type="button"
                onClick={() => setActiveTradeTab("buy")}
              >
                Buy {stock.symbol}
              </button>
              <button
                className={activeTradeTab === "sell" ? "active" : ""}
                type="button"
                disabled={isSecondaryTradeDisabled}
                onClick={() => setActiveTradeTab("sell")}
              >
                {secondaryTradeLabel} {stock.symbol}
              </button>
            </div>
            <label className="field">
              <span>Amount</span>
              <input
                type="number"
                min="0"
                max={activeTradeTab === "sell" && !stock.shortable && hasOpenPosition ? sellLimit : undefined}
                step="0.01"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="$0.00"
              />
            </label>
            {hasOpenPosition ? <p className="field-help">Available position value: {currency(sellLimit)}</p> : null}
            <div className="rail-button-stack">
              <button
                className="primary-button"
                type="button"
                disabled={activeTradeTab === "sell" ? isSecondaryTradeDisabled : isSubmitting || !stock.tradable}
                onClick={() => executeTrade(activeTradeTab === "sell" ? "sell" : "buy")}
              >
                {activeTradeTab === "sell" ? secondaryTradeLabel : "Buy"}
              </button>
              <button className="danger-button" type="button" disabled={isSubmitting || !hasOpenPosition} onClick={() => executeTrade("close")}>Close position</button>
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
                {transactions.slice(0, 5).map((transaction) => (
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
                {!transactions.length && !allocationError ? <p className="muted">No stock transactions yet.</p> : null}
              </div>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
