import { useEffect, useState } from "react";
import BasktCard from "../components/BasktCard";
import { EmptyState, ErrorBanner, LoadingState } from "../components/Status";
import { apiRequest } from "../lib/api";

export default function BasktAccountPage({ cognitoUserId, onBack, onOpenBaskt }) {
  const [account, setAccount] = useState(null);
  const [portfolios, setPortfolios] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    apiRequest(`/baskt-accounts/${encodeURIComponent(cognitoUserId)}/profile`)
      .then((payload) => {
        if (!ignore) {
          setAccount(payload.baskt_account);
          setPortfolios(Array.isArray(payload.model_portfolios) ? payload.model_portfolios : []);
        }
      })
      .catch((requestError) => {
        if (!ignore) setError(requestError?.message || "Could not load this profile.");
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });
    return () => { ignore = true; };
  }, [cognitoUserId]);

  if (isLoading) {
    return <LoadingState title="Loading profile" message="Fetching this member’s Baskts." />;
  }

  return (
    <div className="page-stack baskt-account-page">
      <div className="detail-header">
        <button className="ghost-button" type="button" onClick={onBack}>Back</button>
      </div>
      <ErrorBanner message={error} />
      {account && (
        <>
          <section className="baskt-account-profile">
            <h1>{account.display_name}</h1>
            <p>{account.description || "No description yet."}</p>
          </section>
          <section>
            <div className="section-heading">
              <div>
                <h2>{portfolios.length} {portfolios.length === 1 ? "portfolio" : "portfolios"}</h2>
              </div>
            </div>
            {portfolios.length ? (
              <div className="baskt-grid">
                {portfolios.map((portfolio) => (
                  <BasktCard
                    key={portfolio.portfolio_id}
                    baskt={portfolio}
                    onOpen={onOpenBaskt}
                  />
                ))}
              </div>
            ) : (
              <EmptyState title="No Baskts yet" message="This member has not created any Baskts." />
            )}
          </section>
        </>
      )}
    </div>
  );
}
