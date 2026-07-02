import { useEffect, useMemo, useState } from "react";
import EquityChart from "../components/EquityChart";
import { ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { percent } from "../lib/format";

const defaultPosition = { symbol: "", target_weight: 1, direction: 1, leverage: 1, shortable: false };
const MIN_BACKTEST_DATE = "1970-01-01";

function formatDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function getDefaultBacktestStartDate() {
  const date = new Date();
  date.setFullYear(date.getFullYear() - 1);
  return formatDateInput(date);
}

function getAllocationTone(totalWeight) {
  if (Math.abs(totalWeight - 1) < 0.0001) {
    return "ready";
  }

  if (totalWeight > 1) {
    return "over";
  }

  return "under";
}

function getAllocationMessage(totalWeight) {
  if (Math.abs(totalWeight - 1) < 0.0001) {
    return "Fully allocated";
  }

  if (totalWeight > 1) {
    return `${percent((totalWeight - 1) * 100)} over target`;
  }

  return `${percent((1 - totalWeight) * 100)} left to allocate`;
}

function normalizePosition(position) {
  return {
    symbol: String(position.symbol || "").toUpperCase(),
    target_weight: Number(position.target_weight ?? position.weight ?? 0),
    direction: Number(position.direction || 1),
    leverage: 1,
    shortable: Boolean(position.shortable),
  };
}

export default function MakeABaskt({ editingPortfolioId, onSaved }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [positions, setPositions] = useState([]);
  const [stockSearch, setStockSearch] = useState("");
  const [backtestStartDate, setBacktestStartDate] = useState(getDefaultBacktestStartDate);
  const [backtestEndDate, setBacktestEndDate] = useState(() => formatDateInput(new Date()));
  const [assets, setAssets] = useState([]);
  const [backtest, setBacktest] = useState(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isAssetsLoading, setIsAssetsLoading] = useState(true);
  const [isPortfolioLoading, setIsPortfolioLoading] = useState(Boolean(editingPortfolioId));
  const [isBacktesting, setIsBacktesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const totalWeight = useMemo(
    () => positions.reduce((total, position) => total + Number(position.target_weight || 0), 0),
    [positions]
  );

  const validPositions = useMemo(
    () => positions.map(normalizePosition).filter((position) => position.symbol && position.target_weight > 0),
    [positions]
  );
  const searchedAssets = useMemo(() => {
    const query = stockSearch.trim().toUpperCase();
    const existingSymbols = new Set(positions.map((position) => position.symbol));

    if (!query) {
      return [];
    }

    return assets
      .filter((asset) => asset.symbol?.includes(query) && !existingSymbols.has(asset.symbol));
  }, [assets, positions, stockSearch]);
  const allocationTone = getAllocationTone(totalWeight);
  const todayDate = useMemo(() => formatDateInput(new Date()), []);
  const isBacktestDateRangeValid = backtestStartDate && backtestEndDate && backtestEndDate >= backtestStartDate;
  const isFullyAllocated = Math.abs(totalWeight - 1) < 0.0001;

  useEffect(() => {
    const controller = new AbortController();

    if (!editingPortfolioId) {
      setName("");
      setDescription("");
      setPositions([]);
      setIsPortfolioLoading(false);
      return () => controller.abort();
    }

    async function loadPortfolio() {
      try {
        setIsPortfolioLoading(true);
        setError("");
        const payload = await apiRequest(`/model-portfolios/${editingPortfolioId}`, {
          signal: controller.signal,
        });
        setName(payload.portfolio_name || "");
        setDescription(payload.description || "");
        setPositions(
          payload.position_history?.at(-1)?.positions?.map(normalizePosition) || []
        );
      } catch (portfolioError) {
        if (portfolioError?.name !== "AbortError") {
          setError(portfolioError?.message || "Could not load this Baskt for editing.");
        }
      } finally {
        if (!controller.signal.aborted) {
          setIsPortfolioLoading(false);
        }
      }
    }

    void loadPortfolio();
    return () => controller.abort();
  }, [editingPortfolioId]);

  const assetsBySymbol = useMemo(
    () =>
      new Map(
        assets.map((asset) => [
          String(asset.symbol || "").toUpperCase(),
          asset,
        ])
      ),
    [assets]
  );

  useEffect(() => {
    if (!assetsBySymbol.size) {
      return;
    }

    setPositions((current) =>
      current.map((position) => {
        const asset = assetsBySymbol.get(position.symbol);
        const shortable = Boolean(asset?.shortable);
        return {
          ...position,
          shortable,
          direction: shortable ? position.direction : 1,
        };
      })
    );
  }, [assetsBySymbol]);

  useEffect(() => {
    let ignore = false;
    async function loadAssets() {
      try {
        setIsAssetsLoading(true);
        const payload = await apiRequest("/backtest/tradeable-fractionable-us-baskt-assets");
        if (!ignore) {
          setAssets(Array.isArray(payload) ? payload : []);
        }
      } catch (assetError) {
        if (!ignore) {
          setError(assetError?.message || "Could not load tradeable assets.");
        }
      } finally {
        if (!ignore) {
          setIsAssetsLoading(false);
        }
      }
    }
    loadAssets();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!validPositions.length || !isBacktestDateRangeValid || !isFullyAllocated) {
      setBacktest(null);
      return undefined;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      try {
        setIsBacktesting(true);
        const query = toQuery({
          start_date: backtestStartDate,
          end_date: backtestEndDate,
          positions: JSON.stringify(validPositions),
        });
        const payload = await apiRequest(`/backtest${query}`, { signal: controller.signal });
        setBacktest(payload);
      } catch (backtestError) {
        if (backtestError.name !== "AbortError") {
          setError(backtestError?.message || "Backtest failed.");
        }
      } finally {
        setIsBacktesting(false);
      }
    }, 450);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [validPositions, backtestStartDate, backtestEndDate, isBacktestDateRangeValid, isFullyAllocated]);

  function updateBacktestStartDate(value) {
    setBacktestStartDate(value);
    setBacktestEndDate((currentEndDate) => {
      if (currentEndDate && currentEndDate >= value) {
        return currentEndDate;
      }

      return value;
    });
  }

  function updatePosition(index, field, value) {
    setPositions((current) =>
      current.map((position, positionIndex) =>
        positionIndex === index ? { ...position, [field]: value } : position
      )
    );
  }

  function getRemainingWeight(currentPositions = positions) {
    const currentTotal = currentPositions.reduce(
      (total, position) => total + Number(position.target_weight || 0),
      0
    );
    return Math.max(0, 1 - currentTotal);
  }

  function addAssetPosition(asset) {
    if (!asset?.symbol) {
      return;
    }

    setPositions((current) => {
      if (current.some((position) => position.symbol === asset.symbol)) {
        return current;
      }

      return [
        ...current,
        {
          ...defaultPosition,
          symbol: asset.symbol,
          target_weight: getRemainingWeight(current),
          shortable: Boolean(asset.shortable),
        },
      ];
    });
  }

  function updatePositionDirection(index, value) {
    const direction = Number(value);
    setPositions((current) =>
      current.map((position, positionIndex) => {
        if (positionIndex !== index) {
          return position;
        }
        if (direction === -1 && !position.shortable) {
          return { ...position, direction: 1 };
        }
        return { ...position, direction };
      })
    );
  }

  function removePosition(index) {
    setPositions((current) => current.filter((_, positionIndex) => positionIndex !== index));
  }

  async function saveBaskt(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (!name.trim() && !editingPortfolioId) {
      setError("Please name your Baskt before saving.");
      return;
    }

    if (!validPositions.length) {
      setError("Add at least one valid stock position.");
      return;
    }

    try {
      setIsSaving(true);
      const payload = editingPortfolioId
        ? { positions: validPositions, description }
        : { name: name.trim(), description, positions: validPositions };

      await apiRequest(
        editingPortfolioId ? `/model-portfolios/${editingPortfolioId}` : "/model-portfolios",
        {
          method: editingPortfolioId ? "PUT" : "POST",
          body: JSON.stringify(payload),
        }
      );
      setSuccess(editingPortfolioId ? "Baskt updated." : "Baskt saved.");
      onSaved?.();
    } catch (saveError) {
      setError(saveError?.message || "Could not save this Baskt.");
    } finally {
      setIsSaving(false);
    }
  }

  if (isAssetsLoading || isPortfolioLoading) {
    return (
      <LoadingState
        title={isPortfolioLoading ? "Loading Baskt" : "Preparing assets"}
        message={isPortfolioLoading ? "Fetching the latest portfolio data." : "Loading fractionable US stocks."}
      />
    );
  }

  return (
    <form className="make-layout" onSubmit={saveBaskt}>
      <section className="builder-panel">
        <ErrorBanner message={error} />
        <SuccessBanner message={success} />

        <div className="builder-hero">
          <div>
            <p className="eyebrow">{editingPortfolioId ? "Update Baskt" : "Make a Baskt"}</p>
            <h2>{editingPortfolioId ? name : "Build a portfolio that behaves on purpose."}</h2>
            <p>
              Choose tradeable US stocks, set target weights, and let the backtest refresh as you edit.
            </p>
          </div>
          <div className={`allocation-badge ${allocationTone}`}>
            <span>{percent(totalWeight * 100)}</span>
            <small>{getAllocationMessage(totalWeight)}</small>
          </div>
        </div>

        <div className="portfolio-fields">
          {!editingPortfolioId ? (
            <label className="field">
              <span>Baskt name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="AI hyperscalers"
                required
              />
            </label>
          ) : null}
          <label className="field">
            <span>Description</span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What is the thesis for this Baskt?"
              rows="3"
            />
          </label>
        </div>

        <div className="allocation-toolbar">
          <div>
            <p className="eyebrow">Allocation</p>
            <h3>{positions.length} position{positions.length === 1 ? "" : "s"}</h3>
          </div>
        </div>

        <section className="stock-search-panel">
          <label className="field">
            <span>Search stocks</span>
            <input
              value={stockSearch}
              onChange={(event) => setStockSearch(event.target.value)}
              placeholder="Search by symbol, like MSFT or NVDA"
              autoComplete="off"
            />
          </label>
          {stockSearch.trim() ? (
            <div className="stock-results">
              {searchedAssets.length ? (
                searchedAssets.map((asset) => (
                  <button
                    key={asset.symbol}
                    type="button"
                    className="stock-result"
                    onClick={() => addAssetPosition(asset)}
                  >
                    <strong>{asset.symbol}</strong>
                    <span>{String(asset.stock_class || "US equity").replace("_", " ")}</span>
                    <small>{asset.fractionable ? "Fractionable" : "Whole shares"}</small>
                  </button>
                ))
              ) : (
                <p className="stock-search-empty">No matching tradeable stocks found.</p>
              )}
            </div>
          ) : null}
        </section>

        <div className="positions-editor modern">
          <div className="position-row position-row-header" aria-hidden="true">
            <span>Stock</span>
            <span>Target</span>
            <span>Side</span>
            <span>Leverage</span>
            <span />
          </div>
          {positions.map((position, index) => (
            <div className="position-row" key={index}>
              <div className="symbol-cell">
                <span>Symbol</span>
                <strong>{position.symbol}</strong>
              </div>
              <label>
                <span>Weight</span>
                <div className="percent-input">
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={Number(position.target_weight) * 100}
                    onChange={(event) =>
                      updatePosition(index, "target_weight", Number(event.target.value) / 100)
                    }
                    required
                  />
                  <strong>%</strong>
                </div>
              </label>
              <label>
                <span>Side</span>
                <select value={position.direction} onChange={(event) => updatePositionDirection(index, event.target.value)}>
                  <option value={1}>Long</option>
                  <option value={-1} disabled={!position.shortable}>Short</option>
                </select>
                {!position.shortable ? (
                  <small className="field-help">Shorting unavailable for this stock.</small>
                ) : null}
              </label>
              <label>
                <span>Leverage</span>
                <input value="1x" disabled />
              </label>
              <button className="icon-button" type="button" onClick={() => removePosition(index)} aria-label="Remove position">
                x
              </button>
            </div>
          ))}
        </div>
        {!positions.length ? (
          <div className="allocation-empty">
            Search for a stock above to start building this Baskt.
          </div>
        ) : null}

        <div className="builder-actions">
          <div>
            <strong>{validPositions.length}</strong>
            <span>valid position{validPositions.length === 1 ? "" : "s"} ready to save</span>
          </div>
          <button className="primary-button" type="submit" disabled={isSaving}>
            {isSaving ? "Saving..." : editingPortfolioId ? "Update Baskt" : "Save Baskt"}
          </button>
        </div>
      </section>

      <aside className="insights-panel">
        <div className={`allocation-review ${allocationTone}`}>
          <p className="eyebrow">Portfolio check</p>
          <strong>{percent(totalWeight * 100)}</strong>
          <span>{getAllocationMessage(totalWeight)}</span>
          <div className="allocation-track">
            <span style={{ width: `${Math.min(totalWeight * 100, 100)}%` }} />
          </div>
        </div>

        <section className="panel inset">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Backtest</p>
              <h2>{isBacktesting && isFullyAllocated ? "Running..." : "Backtest result"}</h2>
            </div>
          </div>
          <div className="backtest-date-grid">
            <label className="field">
              <span>Start date</span>
              <input
                type="date"
                min={MIN_BACKTEST_DATE}
                max={todayDate}
                value={backtestStartDate}
                onChange={(event) => updateBacktestStartDate(event.target.value)}
              />
            </label>
            <label className="field">
              <span>End date</span>
              <input
                type="date"
                min={backtestStartDate || MIN_BACKTEST_DATE}
                max={todayDate}
                value={backtestEndDate}
                onChange={(event) => setBacktestEndDate(event.target.value)}
              />
            </label>
          </div>
          {isFullyAllocated ? (
            <>
              <EquityChart
                equity={backtest?.cumulative_returns || []}
                timestamps={[]}
                valueType="decimalPercent"
                variant="compact"
                ariaLabel="Backtest cumulative returns chart"
              />
              <div className="backtest-metrics">
                <div>
                  <span>Return</span>
                  <strong>{percent(Number(backtest?.final_cumulative_return || 0) * 100)}</strong>
                </div>
                <div>
                  <span>CAGR</span>
                  <strong>{percent(Number(backtest?.cagr || 0) * 100)}</strong>
                </div>
                <div>
                  <span>Volatility</span>
                  <strong>{percent(Number(backtest?.annualized_volatility || 0) * 100)}</strong>
                </div>
                <div>
                  <span>Leverage-adjusted direction tilt</span>
                  <strong>{percent(Number(backtest?.leverage_adjusted_direction || 0) * 100)}</strong>
                </div>
                <div>
                  <span>Alpha</span>
                  <strong>{percent(Number(backtest?.alpha || 0) * 100)}</strong>
                </div>
                <div>
                  <span>Beta</span>
                  <strong>{Number(backtest?.beta || 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span>Sharpe ratio</span>
                  <strong>{Number(backtest?.sharpe_ratio || 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span>Maximum drawdown</span>
                  <strong>{percent(Number(backtest?.maximum_drawdown || 0) * 100)}</strong>
                </div>
                <div>
                  <span>Maximum drawdown duration</span>
                  <strong>{Number(backtest?.maximum_drawdown_duration || 0).toFixed(1)} days</strong>
                </div>
              </div>
            </>
          ) : (
            <div className="backtest-blank" aria-live="polite" />
          )}
        </section>
      </aside>
    </form>
  );
}
