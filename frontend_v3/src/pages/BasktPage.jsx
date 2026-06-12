import { useEffect, useMemo, useState } from "react";
import PositionsTable from "../components/PositionsTable";
import { EmptyState, ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { currency, formatDate, formatDateTime, percent } from "../lib/format";
import { getCurrentUserClaims } from "../lib/session";

export default function BasktPage({ portfolioId, onBack, onUpdate }) {
  const [baskt, setBaskt] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const claims = useMemo(() => getCurrentUserClaims(), []);
  const isOwner = claims?.sub && baskt?.portfolio_owner_cognito_user_id === claims.sub;
  const latestSnapshot = baskt?.position_history?.at(-1);

  async function loadBaskt() {
    const payload = await apiRequest(`/model-portfolios/${portfolioId}`);
    setBaskt(payload);

    const query = toQuery({
      portfolio_owner_cognito_user_id: payload.portfolio_owner_cognito_user_id,
    });
    const transactionPayload = await apiRequest(
      `/account-analytics/portfolios/${portfolioId}/transactions${query}`
    );
    setTransactions(transactionPayload?.list_transaction || []);
  }

  useEffect(() => {
    let ignore = false;

    async function run() {
      try {
        setIsLoading(true);
        await loadBaskt();
      } catch (basktError) {
        if (!ignore) {
          setError(basktError?.message || "Could not load this Baskt.");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    run();
    return () => {
      ignore = true;
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
      await loadBaskt();
    } catch (tradeError) {
      setError(tradeError?.message || "Trade request failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) {
    return <LoadingState title="Loading Baskt" message="Fetching positions and transactions." />;
  }

  if (!baskt) {
    return <EmptyState title="Baskt unavailable" message="This portfolio could not be found." />;
  }

  return (
    <div className="page-stack">
      <div className="detail-header">
        <button className="ghost-button" type="button" onClick={onBack}>Back</button>
        {isOwner ? <button className="primary-button" type="button" onClick={() => onUpdate(baskt)}>Update</button> : null}
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
          <div className="table-wrap compact-table">
            <table>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Amount</th>
                  <th>Filled</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((transaction) => (
                  <tr key={transaction.transaction_id}>
                    <td>{transaction.transaction_type}</td>
                    <td>{currency(transaction.transaction_amount)}</td>
                    <td>{percent(transaction.transaction_filled_percent)}</td>
                    <td>{formatDateTime(transaction.transaction_date)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!transactions.length ? <p className="muted">No transactions yet.</p> : null}
          </div>
        </div>
      </section>
    </div>
  );
}
