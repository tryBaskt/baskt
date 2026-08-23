import { useEffect, useState } from "react";
import BasktCard from "../components/BasktCard";
import { EmptyState, ErrorBanner, LoadingState } from "../components/Status";
import { apiRequest } from "../lib/api";

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
          {baskts.map((baskt) => (
            <BasktCard
              key={baskt.portfolio_id}
              baskt={baskt}
              onOpen={onOpenBaskt}
            />
          ))}
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
          {sharedBaskts.map((baskt) => (
            <BasktCard
              key={baskt.portfolio_id}
              baskt={baskt}
              badge="Shared"
              onOpen={onOpenBaskt}
            />
          ))}
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
