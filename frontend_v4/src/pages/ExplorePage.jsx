import { useState } from "react";
import { ErrorBanner } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { formatDate } from "../lib/format";

const PAGE_SIZE = 12;

export default function ExplorePage({ onOpenBaskt, onOpenStock, onOpenUser }) {
  const [query, setQuery] = useState("");
  const [modelPortfolios, setModelPortfolios] = useState([]);
  const [stocks, setStocks] = useState([]);
  const [users, setUsers] = useState([]);
  const [userTotal, setUserTotal] = useState(0);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [searchedQuery, setSearchedQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  async function searchExplore(nextOffset = 0) {
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setModelPortfolios([]);
      setStocks([]);
      setUsers([]);
      setUserTotal(0);
      setTotal(0);
      setOffset(0);
      setSearchedQuery("");
      setError("");
      return;
    }

    try {
      setIsLoading(true);
      setError("");
      setSearchedQuery(normalizedQuery);
      const searchParams = toQuery({
        query: normalizedQuery,
        limit: PAGE_SIZE,
        offset: nextOffset,
      });
      const payload = await apiRequest(`/search${searchParams}`);
      const modelPortfolioPayload = payload?.model_portfolios || {};
      setModelPortfolios(modelPortfolioPayload.model_portfolios || []);
      setStocks(payload?.stocks || []);
      setUsers(payload?.baskt_accounts?.baskt_accounts || []);
      setUserTotal(Number(payload?.baskt_accounts?.total) || 0);
      setTotal(Number(modelPortfolioPayload.total) || 0);
      setOffset(Number(modelPortfolioPayload.offset) || 0);
    } catch (searchError) {
      setError(searchError?.message || "Could not search Baskts and stocks.");
      setModelPortfolios([]);
      setStocks([]);
      setUsers([]);
      setUserTotal(0);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    searchExplore(0);
  }

  const firstResult = total ? offset + 1 : 0;
  const lastResult = Math.min(offset + modelPortfolios.length, total);
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + modelPortfolios.length < total;
  const hasResults = users.length > 0 || modelPortfolios.length > 0 || stocks.length > 0;

  return (
    <div className="page-stack explore-page">
      <section className="section-heading explore-heading">
        <div>
          <p className="eyebrow">Explore</p>
          <h2>Find people, Baskts, and stocks</h2>
        </div>
      </section>

      <form className="explore-search-form" onSubmit={handleSubmit}>
        <label htmlFor="model-portfolio-search">Search people, Baskts &amp; stocks</label>
        <div className="explore-search-control">
          <input
            id="model-portfolio-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by display name, Baskt, description, or stock symbol"
            autoComplete="off"
          />
          <button className="primary-button" type="submit" disabled={isLoading || !query.trim()}>
            {isLoading ? "Searching..." : "Search"}
          </button>
        </div>
      </form>

      <ErrorBanner message={error} />

      <section className="explore-results" aria-live="polite" aria-busy={isLoading}>
        {isLoading ? (
          <div className="explore-message">
            <span className="loader" />
            <p>Searching Baskts and stocks...</p>
          </div>
        ) : searchedQuery && hasResults ? (
          <>
            <div className="explore-results-header">
              <div>
                <p className="eyebrow">Search results</p>
                <h3>Results for &ldquo;{searchedQuery}&rdquo;</h3>
              </div>
              <span>
                {userTotal} {userTotal === 1 ? "person" : "people"} &middot; {stocks.length} {stocks.length === 1 ? "stock" : "stocks"} &middot; {total} {total === 1 ? "Baskt" : "Baskts"}
              </span>
            </div>

            {users.length > 0 && (
              <div className="explore-result-group">
                <h4>People</h4>
                <div className="explore-results-list">
                  {users.map((user) => (
                    <button
                      className="explore-result explore-user-result"
                      type="button"
                      onClick={() => onOpenUser(user.cognito_user_id)}
                      key={user.cognito_user_id}
                    >
                      <div className="explore-result-copy">
                        <span className="baskt-badge">Member</span>
                        <h3>{user.display_name}</h3>
                        <p>{user.description || "Baskt member"}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {stocks.length > 0 && (
              <div className="explore-result-group">
                <h4>Stocks</h4>
                <div className="explore-results-list">
                  {stocks.map((stock) => (
                    <button
                      key={stock.stock_id}
                      className="explore-result explore-stock-result"
                      type="button"
                      onClick={() => onOpenStock(stock)}
                    >
                      <div className="explore-result-copy">
                        <span className="baskt-badge">Stock</span>
                        <h3>{stock.symbol}</h3>
                        <p>{String(stock.stock_class || "US equity").replaceAll("_", " ")}</p>
                      </div>
                      <div className="stock-capabilities">
                        {stock.tradable && <span>Tradable</span>}
                        {stock.fractionable && <span>Fractionable</span>}
                        {stock.shortable && <span>Shortable</span>}
                        {stock.marginable && <span>Marginable</span>}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {modelPortfolios.length > 0 && (
              <div className="explore-result-group">
                <div className="explore-group-heading">
                  <h4>Baskts</h4>
                  <span>{firstResult}-{lastResult} of {total}</span>
                </div>
                <div className="explore-results-list">
                  {modelPortfolios.map((modelPortfolio) => (
                    <button
                      key={modelPortfolio.portfolio_id}
                      className="explore-result"
                      type="button"
                      onClick={() => onOpenBaskt(modelPortfolio.portfolio_id)}
                    >
                      <div className="explore-result-copy">
                        <span className="baskt-badge">Baskt</span>
                        <h3>{modelPortfolio.portfolio_name}</h3>
                        <p>{modelPortfolio.description || "No description yet."}</p>
                      </div>
                      <div className="explore-result-meta">
                        <span className="portfolio-owner-name">
                          By {modelPortfolio.portfolio_owner_display_name || "Baskt member"}
                        </span>
                        <span>Created <strong>{formatDate(modelPortfolio.created_at)}</strong></span>
                        <span>Updated <strong>{formatDate(modelPortfolio.updated_at)}</strong></span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {(hasPreviousPage || hasNextPage) && (
              <div className="explore-pagination">
                <button
                  className="ghost-button"
                  type="button"
                  disabled={!hasPreviousPage || isLoading}
                  onClick={() => searchExplore(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </button>
                <button
                  className="ghost-button"
                  type="button"
                  disabled={!hasNextPage || isLoading}
                  onClick={() => searchExplore(offset + PAGE_SIZE)}
                >
                  Next
                </button>
              </div>
            )}
          </>
        ) : searchedQuery ? (
          <div className="explore-message">
            <h3>No matches found</h3>
            <p>Try a different display name, Baskt, description, or stock symbol.</p>
          </div>
        ) : (
          <div className="explore-message explore-message--initial">
            <h3>Explore the market</h3>
            <p>Enter a display name, Baskt, description, or stock symbol.</p>
          </div>
        )}
      </section>
    </div>
  );
}
