import { useEffect, useMemo, useState } from "react";
import EquityChart from "../components/EquityChart";
import { EmptyState, ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest } from "../lib/api";
import { currency, formatDateTime, percent } from "../lib/format";

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
  const transactions = allocationAnalytics?.transaction_history || [];
  const hasAllocation =
    allocationAnalytics?.equity !== null &&
    allocationAnalytics?.equity !== undefined;
  const sellLimit = hasAllocation ? Math.max(0, Number(allocationAnalytics.equity)) : 0;
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
        `/account-analytics/stocks/${stockId}`,
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
        `/account-analytics/stocks/${stockId}/analytics`,
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

    void loadStockDetails(controller.signal).then((loadedStock) => {
      if (!loadedStock || controller.signal.aborted) {
        setIsAnalyticsLoading(false);
        return;
      }

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

    void loadAllocationAnalytics(controller.signal);

    return () => controller.abort();
  }, [stockId]);

  async function executeTrade(action) {
    setTradeError("");
    setSuccess("");

    const needsAmount = action !== "close";
    const numericAmount = Number(amount);
    if (needsAmount && (!Number.isFinite(numericAmount) || numericAmount <= 0)) {
      setTradeError("Enter an amount greater than zero.");
      return;
    }
    if (action === "sell" && numericAmount > sellLimit) {
      setTradeError(`Sell amount cannot exceed ${currency(sellLimit)}.`);
      return;
    }

    try {
      setIsSubmitting(true);
      await apiRequest(`/trade-execution/stocks/${stock.stock_id}/${action}`, {
        method: "POST",
        body: JSON.stringify({
          symbol: stock.symbol,
          ...(needsAmount ? { amount: numericAmount } : {}),
        }),
      });
      setSuccess(
        action === "close"
          ? `Close request submitted for ${stock.symbol}.`
          : `${action === "buy" ? "Buy" : "Sell"} request submitted.`
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
    <div className="page-stack stock-detail-page">
      <div className="detail-header">
        <button className="ghost-button" type="button" onClick={onBack}>Back</button>
      </div>

      <ErrorBanner message={tradeError} />
      <SuccessBanner message={success} />

      <section className="hero-band stock-hero">
        <div className="stock-identity">
          <span className="stock-symbol-mark">{stock.symbol}</span>
          <div>
            <p className="eyebrow">Stock detail</p>
            <h2>{stock.symbol}</h2>
            <p>{String(stock.stock_class || "US equity").replaceAll("_", " ")}</p>
          </div>
        </div>
        <div className="stock-capabilities" aria-label="Stock capabilities">
          {capabilities.map((capability) => <span key={capability}>{capability}</span>)}
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Stock performance</p>
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
          <div className="model-performance-layout">
            <EquityChart
              equity={prices}
              timestamps={selectedAnalytics?.timestamp || []}
              valueType="currency"
              variant="wide"
              align="left"
              ariaLabel={`${selectedPeriod} ${stock.symbol} price chart`}
              emptyMessage="Stock prices are unavailable for this period."
            />
            <div className="model-performance-metrics" aria-label={`${selectedPeriod} stock metrics`}>
              <div>
                <span>Cumulative return</span>
                <strong className={getReturnTone(periodReturn)}>
                  {Number.isFinite(periodReturn) ? percent(periodReturn) : "Not available"}
                </strong>
                <small>{selectedPeriod === "all" ? "All time" : selectedPeriod}</small>
              </div>
              <div>
                <span>CAGR</span>
                <strong className={getReturnTone(selectedAnalytics?.cagr)}>
                  {selectedAnalytics?.cagr !== null && selectedAnalytics?.cagr !== undefined
                    ? percent(Number(selectedAnalytics.cagr) * 100)
                    : "Not available"}
                </strong>
              </div>
              <div>
                <span>Annualized volatility</span>
                <strong className="metric-accent">
                  {selectedAnalytics?.annualized_volatility !== null && selectedAnalytics?.annualized_volatility !== undefined
                    ? percent(Number(selectedAnalytics.annualized_volatility) * 100)
                    : "Not available"}
                </strong>
              </div>
              <div>
                <span>Direction tilt</span>
                <strong className="metric-accent">
                  {selectedAnalytics?.leverage_adjusted_direction !== null && selectedAnalytics?.leverage_adjusted_direction !== undefined
                    ? percent(Number(selectedAnalytics.leverage_adjusted_direction) * 100)
                    : "Not available"}
                </strong>
                <small>Long + / short -</small>
              </div>
            </div>
          </div>
        )}
      </section>

      <ErrorBanner message={allocationError} />
      {isAllocationLoading ? (
        <section className="analytics-bar" aria-live="polite" aria-busy="true">
          <div><span>Your allocation</span><strong>Loading...</strong><small>Fetching holding and activity</small></div>
        </section>
      ) : hasAllocation ? (
        <section className="analytics-bar" aria-label={`${stock.symbol} allocation analytics`}>
          <div>
            <span>Position value</span>
            <strong>{currency(allocationAnalytics.equity, "Not available")}</strong>
            <small>Cost basis {currency(allocationAnalytics.total_cost_basis, "Not available")}</small>
          </div>
          <div>
            <span>Profit/Loss</span>
            <strong className={getReturnTone(allocationAnalytics.profit_loss)}>
              {currency(allocationAnalytics.profit_loss, "Not available")}
            </strong>
            <small>Current value minus basis</small>
          </div>
          <div>
            <span>Profit/Loss %</span>
            <strong className={getReturnTone(allocationAnalytics.profit_loss_percent)}>
              {percent(Number(allocationAnalytics.profit_loss_percent) * 100)}
            </strong>
            <small>Return on allocated basis</small>
          </div>
        </section>
      ) : (
        <section className="stock-empty-allocation">
          <div>
            <p className="eyebrow">Your allocation</p>
            <h2>You do not own {stock.symbol} yet</h2>
            <p>Enter an amount below to place your first buy.</p>
          </div>
        </section>
      )}

      <section className="split-grid stock-activity-grid">
        <div className="panel stock-trade-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Trade {stock.symbol}</p>
              <h2>Buy or sell</h2>
            </div>
          </div>
          <label className="field">
            <span>Amount</span>
            <input
              type="number"
              min="0"
              max={hasAllocation ? sellLimit : undefined}
              step="0.01"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="$0.00"
            />
          </label>
          {hasAllocation ? <p className="field-help">Available position value: {currency(sellLimit)}</p> : null}
          <div className="button-row">
            <button className="primary-button" type="button" disabled={isSubmitting || !stock.tradable} onClick={() => executeTrade("buy")}>Buy</button>
            <button className="ghost-button" type="button" disabled={isSubmitting || !hasAllocation} onClick={() => executeTrade("sell")}>Sell</button>
            <button className="danger-button" type="button" disabled={isSubmitting || !hasAllocation} onClick={() => executeTrade("close")}>Close position</button>
          </div>
        </div>

        <div className="panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Transactions</p>
              <h2>Stock activity</h2>
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
                      <td>{transaction.requested_amount === null ? "Close" : currency(transaction.requested_amount)}</td>
                      <td>{currency(transaction.cost_basis)}</td>
                      <td>{percent(transaction.order_fill_percent)}</td>
                      <td>{transaction.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!transactions.length && !allocationError ? <p className="muted">No stock transactions yet.</p> : null}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
