import { useState } from "react";
import { ErrorBanner } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { formatDate } from "../lib/format";

const PAGE_SIZE = 12;

export default function ExplorePage({ onOpenBaskt }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [searchedQuery, setSearchedQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  async function searchModelPortfolios(nextOffset = 0) {
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      setResults([]);
      setTotal(0);
      setOffset(0);
      setSearchedQuery("");
      setError("");
      return;
    }

    try {
      setIsLoading(true);
      setError("");
      const searchParams = toQuery({
        query: normalizedQuery,
        limit: PAGE_SIZE,
        offset: nextOffset,
      });
      const payload = await apiRequest(`/search/model-portfolios${searchParams}`);
      setResults(payload?.model_portfolios || []);
      setTotal(Number(payload?.total) || 0);
      setOffset(Number(payload?.offset) || 0);
      setSearchedQuery(normalizedQuery);
    } catch (searchError) {
      setError(searchError?.message || "Could not search model portfolios.");
      setResults([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    searchModelPortfolios(0);
  }

  const firstResult = total ? offset + 1 : 0;
  const lastResult = Math.min(offset + results.length, total);
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + results.length < total;

  return (
    <div className="page-stack explore-page">
      <section className="section-heading explore-heading">
        <div>
          <p className="eyebrow">Explore</p>
          <h2>Find your next Baskt</h2>
        </div>
      </section>

      <form className="explore-search-form" onSubmit={handleSubmit}>
        <label htmlFor="model-portfolio-search">Search Baskts</label>
        <div className="explore-search-control">
          <input
            id="model-portfolio-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by name or description"
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
            <p>Searching Baskts...</p>
          </div>
        ) : searchedQuery && results.length ? (
          <>
            <div className="explore-results-header">
              <div>
                <p className="eyebrow">Search results</p>
                <h3>{total} {total === 1 ? "Baskt" : "Baskts"} found</h3>
              </div>
              <span>{firstResult}-{lastResult} of {total}</span>
            </div>

            <div className="explore-results-list">
              {results.map((modelPortfolio) => (
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
                    <span>Created <strong>{formatDate(modelPortfolio.created_at)}</strong></span>
                    <span>Updated <strong>{formatDate(modelPortfolio.updated_at)}</strong></span>
                  </div>
                </button>
              ))}
            </div>

            {(hasPreviousPage || hasNextPage) && (
              <div className="explore-pagination">
                <button
                  className="ghost-button"
                  type="button"
                  disabled={!hasPreviousPage || isLoading}
                  onClick={() => searchModelPortfolios(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </button>
                <button
                  className="ghost-button"
                  type="button"
                  disabled={!hasNextPage || isLoading}
                  onClick={() => searchModelPortfolios(offset + PAGE_SIZE)}
                >
                  Next
                </button>
              </div>
            )}
          </>
        ) : searchedQuery ? (
          <div className="explore-message">
            <h3>No Baskts found</h3>
            <p>Try a different name or description.</p>
          </div>
        ) : (
          <div className="explore-message explore-message--initial">
            <h3>Search the Baskt library</h3>
            <p>Enter a name or description to begin.</p>
          </div>
        )}
      </section>
    </div>
  );
}
