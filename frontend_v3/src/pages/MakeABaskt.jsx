import { useEffect, useMemo, useState } from "react";
import EquityChart from "../components/EquityChart";
import { ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { percent } from "../lib/format";

const defaultPosition = { symbol: "", target_weight: 100, direction: 1, leverage: 1 };

function getAllocationTone(totalWeight) {
  if (Math.abs(totalWeight - 100) < 0.01) {
    return "ready";
  }

  if (totalWeight > 100) {
    return "over";
  }

  return "under";
}

function getAllocationMessage(totalWeight) {
  if (Math.abs(totalWeight - 100) < 0.01) {
    return "Fully allocated";
  }

  if (totalWeight > 100) {
    return `${percent(totalWeight - 100)} over target`;
  }

  return `${percent(100 - totalWeight)} left to allocate`;
}

function normalizePosition(position) {
  return {
    symbol: String(position.symbol || "").toUpperCase(),
    target_weight: Number(position.target_weight || position.weight || 0),
    direction: Number(position.direction || 1),
    leverage: 1,
  };
}

export default function MakeABaskt({ editingBaskt, onSaved }) {
  const [name, setName] = useState(editingBaskt?.portfolio_name || "");
  const [description, setDescription] = useState(editingBaskt?.description || "");
  const [positions, setPositions] = useState(
    editingBaskt?.position_history?.at(-1)?.positions?.map(normalizePosition) || []
  );
  const [stockSearch, setStockSearch] = useState("");
  const [assets, setAssets] = useState([]);
  const [backtest, setBacktest] = useState(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isAssetsLoading, setIsAssetsLoading] = useState(true);
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
      .filter((asset) => asset.symbol?.includes(query) && !existingSymbols.has(asset.symbol))
      .slice(0, 8);
  }, [assets, positions, stockSearch]);
  const allocationTone = getAllocationTone(totalWeight);

  useEffect(() => {
    let ignore = false;
    async function loadAssets() {
      try {
        setIsAssetsLoading(true);
        const payload = await apiRequest("/backtest/tradeable-fractionable-us-baskt-assets");
        if (!ignore) {
          setAssets(payload?.baskt_assets || []);
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
    if (!validPositions.length) {
      setBacktest(null);
      return undefined;
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      try {
        setIsBacktesting(true);
        const endDate = new Date();
        const startDate = new Date();
        startDate.setFullYear(endDate.getFullYear() - 1);
        const query = toQuery({
          start_date: startDate.toISOString().slice(0, 10),
          end_date: endDate.toISOString().slice(0, 10),
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
  }, [validPositions]);

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
    return Math.max(0, 100 - currentTotal);
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
        },
      ];
    });
    setStockSearch("");
  }

  function removePosition(index) {
    setPositions((current) => current.filter((_, positionIndex) => positionIndex !== index));
  }

  async function saveBaskt(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (!name.trim() && !editingBaskt) {
      setError("Please name your Baskt before saving.");
      return;
    }

    if (!validPositions.length) {
      setError("Add at least one valid stock position.");
      return;
    }

    try {
      setIsSaving(true);
      const payload = editingBaskt
        ? { positions: validPositions, description }
        : { name: name.trim(), description, positions: validPositions };

      await apiRequest(
        editingBaskt ? `/model-portfolios/${editingBaskt.portfolio_id}` : "/model-portfolios",
        {
          method: editingBaskt ? "PUT" : "POST",
          body: JSON.stringify(payload),
        }
      );
      setSuccess(editingBaskt ? "Baskt updated." : "Baskt saved.");
      onSaved?.();
    } catch (saveError) {
      setError(saveError?.message || "Could not save this Baskt.");
    } finally {
      setIsSaving(false);
    }
  }

  if (isAssetsLoading) {
    return <LoadingState title="Preparing assets" message="Loading fractionable US stocks." />;
  }

  return (
    <form className="make-layout" onSubmit={saveBaskt}>
      <section className="builder-panel">
        <ErrorBanner message={error} />
        <SuccessBanner message={success} />

        <div className="builder-hero">
          <div>
            <p className="eyebrow">{editingBaskt ? "Update Baskt" : "Make a Baskt"}</p>
            <h2>{editingBaskt ? editingBaskt.portfolio_name : "Build a portfolio that behaves on purpose."}</h2>
            <p>
              Choose tradeable US stocks, set target weights in percent units, and let the backtest refresh as you edit.
            </p>
          </div>
          <div className={`allocation-badge ${allocationTone}`}>
            <span>{percent(totalWeight)}</span>
            <small>{getAllocationMessage(totalWeight)}</small>
          </div>
        </div>

        <div className="portfolio-fields">
          {!editingBaskt ? (
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
                    <span>{String(asset.asset_class || "US equity").replace("_", " ")}</span>
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
                    value={position.target_weight}
                    onChange={(event) => updatePosition(index, "target_weight", event.target.value)}
                    required
                  />
                  <strong>%</strong>
                </div>
              </label>
              <label>
                <span>Side</span>
                <select value={position.direction} onChange={(event) => updatePosition(index, "direction", event.target.value)}>
                  <option value={1}>Long</option>
                  <option value={-1}>Short</option>
                </select>
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
            {isSaving ? "Saving..." : editingBaskt ? "Update Baskt" : "Save Baskt"}
          </button>
        </div>
      </section>

      <aside className="insights-panel">
        <div className={`allocation-review ${allocationTone}`}>
          <p className="eyebrow">Portfolio check</p>
          <strong>{percent(totalWeight)}</strong>
          <span>{getAllocationMessage(totalWeight)}</span>
          <div className="allocation-track">
            <span style={{ width: `${Math.min(totalWeight, 100)}%` }} />
          </div>
        </div>

        <section className="panel inset">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Backtest</p>
              <h2>{isBacktesting ? "Running..." : "1 year result"}</h2>
            </div>
          </div>
          <EquityChart equity={backtest?.cumulative_returns || []} />
          <div className="backtest-metrics">
            <div>
              <span>Return</span>
              <strong>{percent(Number(backtest?.metrics?.final_cumulative_return || 0) * 100)}</strong>
            </div>
            <div>
              <span>CAGR</span>
              <strong>{percent(Number(backtest?.metrics?.cagr || 0) * 100)}</strong>
            </div>
            <div>
              <span>Volatility</span>
              <strong>{percent(Number(backtest?.metrics?.annualized_volatility || 0) * 100)}</strong>
            </div>
          </div>
        </section>
      </aside>
    </form>
  );
}
