import { useEffect, useState } from "react";
import { EmptyState, ErrorBanner, LoadingState } from "../components/Status";
import { apiRequest } from "../lib/api";
import { formatDate } from "../lib/format";

export default function MyBaskts({ onOpenBaskt, onCreateBaskt }) {
  const [baskts, setBaskts] = useState([]);
  const [sharedBaskts, setSharedBaskts] = useState([]);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let ignore = false;

    async function loadBaskts() {
      try {
        setIsLoading(true);
        const [payload, sharedPayload] = await Promise.all([
          apiRequest("/model-portfolios"),
          apiRequest("/model-portfolios/shared-with-me"),
        ]);
        const metadata = Array.isArray(payload) ? payload : [];
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
          setSharedBaskts(Array.isArray(sharedPayload) ? sharedPayload : []);
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

  function renderBasktCard(baskt, badge = "Baskt") {
    return (
      <button
        key={baskt.portfolio_id}
        className="baskt-card"
        type="button"
        onClick={() => onOpenBaskt(baskt.portfolio_id)}
      >
        <span className="baskt-badge">{badge}</span>
        <h3>{baskt.portfolio_name}</h3>
        <p>{baskt.description || "No description yet."}</p>
        <div className="baskt-meta">
          <span>Created <strong>{formatDate(baskt.created_at)}</strong></span>
          <span>Updated <strong>{formatDate(baskt.updated_at)}</strong></span>
        </div>
      </button>
    );
  }

  return (
    <div className="page-stack">
      <ErrorBanner message={error} />
      <section className="section-heading">
        <div>
          <h2>Your portfolio library</h2>
        </div>
        <button className="primary-button" type="button" onClick={onCreateBaskt}>
          Create Baskt
        </button>
      </section>

      {baskts.length ? (
        <div className="baskt-grid">
          {baskts.map((baskt) => renderBasktCard(baskt))}
        </div>
      ) : (
        <EmptyState
          title="No Baskts yet"
          message="Create your first weighted portfolio and backtest it before saving."
          action={<button className="primary-button" type="button" onClick={onCreateBaskt}>Make a Baskt</button>}
        />
      )}

      <section className="section-heading">
        <div>
          <h2>Baskts shared with me</h2>
        </div>
      </section>

      {sharedBaskts.length ? (
        <div className="baskt-grid">
          {sharedBaskts.map((baskt) => renderBasktCard(baskt, "Shared"))}
        </div>
      ) : (
        <EmptyState
          title="No shared Baskts"
          message="Private Baskts shared with you will appear here."
        />
      )}
    </div>
  );
}
