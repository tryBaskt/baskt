import { useEffect, useRef, useState } from "react";
import { apiRequest, toQuery } from "../lib/api";

export default function GlobalSearch({ onOpenBaskt, onOpenStock }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState({ stocks: [], baskts: [] });
  const [isLoading, setIsLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [hasError, setHasError] = useState(false);
  const requestId = useRef(0);

  useEffect(() => {
    const normalizedQuery = query.trim();
    requestId.current += 1;
    const currentRequest = requestId.current;
    if (!normalizedQuery) {
      setResults({ stocks: [], baskts: [] });
      setIsOpen(false);
      setHasError(false);
      return undefined;
    }

    const timer = window.setTimeout(async () => {
      try {
        setIsLoading(true);
        setHasError(false);
        const payload = await apiRequest(`/search${toQuery({ query: normalizedQuery, limit: 6, offset: 0 })}`);
        if (requestId.current !== currentRequest) return;
        setResults({
          stocks: payload?.stocks || [],
          baskts: payload?.model_portfolios?.model_portfolios || [],
        });
        setIsOpen(true);
      } catch {
        if (requestId.current !== currentRequest) return;
        setResults({ stocks: [], baskts: [] });
        setHasError(true);
        setIsOpen(true);
      } finally {
        if (requestId.current === currentRequest) setIsLoading(false);
      }
    }, 260);

    return () => window.clearTimeout(timer);
  }, [query]);

  const hasResults = results.stocks.length > 0 || results.baskts.length > 0;

  function selectResult(callback, value) {
    setIsOpen(false);
    setQuery("");
    callback(value);
  }

  return (
    <div className="global-search" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setIsOpen(false);
    }}>
      <span className="global-search-icon" aria-hidden="true" />
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onFocus={() => query.trim() && setIsOpen(true)}
        placeholder="Search Baskts and stocks"
        aria-label="Search Baskts and stocks"
        aria-expanded={isOpen}
        autoComplete="off"
      />
      {isLoading && <span className="search-status">Searching</span>}
      {isOpen && (
        <div className="global-search-results" role="listbox">
          <div className="search-results-label">Search results</div>
          {hasError ? (
            <div className="search-empty">Error</div>
          ) : hasResults ? (
            <>
              {results.stocks.map((stock) => (
                <button
                  key={stock.stock_id}
                  type="button"
                  role="option"
                  onClick={() => selectResult(onOpenStock, stock.stock_id)}
                >
                  <span className="search-result-symbol">{stock.symbol}</span>
                  <span><strong>{stock.symbol}</strong><small>Stock · {String(stock.stock_class || "US equity").replaceAll("_", " ")}</small></span>
                  <span className="search-result-kind">STOCK</span>
                </button>
              ))}
              {results.baskts.map((baskt) => (
                <button
                  key={baskt.portfolio_id}
                  type="button"
                  role="option"
                  onClick={() => selectResult(onOpenBaskt, baskt.portfolio_id)}
                >
                  <span className="search-result-symbol baskt">B</span>
                  <span><strong>{baskt.portfolio_name}</strong><small>{baskt.description || "Model portfolio"}</small></span>
                  <span className="search-result-kind">BASKT</span>
                </button>
              ))}
            </>
          ) : (
            <div className="search-empty">No Baskts or stocks found</div>
          )}
        </div>
      )}
    </div>
  );
}
