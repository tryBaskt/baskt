import { useEffect, useState } from "react";
import { EmptyState, ErrorBanner, LoadingState } from "../components/Status";
import { apiRequest } from "../lib/api";
import { formatDate } from "../lib/format";

export default function MyBaskts({ onOpenBaskt, onCreateBaskt }) {
  const [baskts, setBaskts] = useState([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let ignore = false;

    async function loadBaskts() {
      try {
        setIsLoading(true);
        const payload = await apiRequest("/model-portfolios");
        const metadata = payload?.list_model_portfolio_metadata || [];
        const detailedBaskts = await Promise.all(
          metadata.map(async (baskt) => {
            try {
              return await apiRequest(`/model-portfolios/${baskt.portfolio_id}`);
            } catch {
              return baskt;
            }
          })
        );
        if (!ignore) {
          setBaskts(detailedBaskts);
        }
      } catch (basktError) {
        if (!ignore) {
          setError(basktError?.message || "Could not load your Baskts.");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    loadBaskts();
    return () => {
      ignore = true;
    };
  }, []);

  if (isLoading) {
    return <LoadingState title="Loading Baskts" message="Fetching your saved portfolios." />;
  }

  return (
    <div className="page-stack">
      <ErrorBanner message={error} />
      <section className="section-heading">
        <div>
          <p className="eyebrow">Saved Baskts</p>
          <h2>Your portfolio library</h2>
        </div>
        <button className="primary-button" type="button" onClick={onCreateBaskt}>
          Create Baskt
        </button>
      </section>

      {baskts.length ? (
        <div className="baskt-grid">
          {baskts.map((baskt) => (
            <button
              key={baskt.portfolio_id}
              className="baskt-card"
              type="button"
              onClick={() => onOpenBaskt(baskt.portfolio_id)}
            >
              <span className="baskt-badge">Baskt</span>
              <h3>{baskt.portfolio_name}</h3>
              <p>{baskt.description || "No description yet."}</p>
              <div className="baskt-meta">
                <span>Created <strong>{formatDate(baskt.created_at)}</strong></span>
                <span>Updated <strong>{formatDate(baskt.updated_at)}</strong></span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No Baskts yet"
          message="Create your first weighted portfolio and backtest it before saving."
          action={<button className="primary-button" type="button" onClick={onCreateBaskt}>Make a Baskt</button>}
        />
      )}
    </div>
  );
}
