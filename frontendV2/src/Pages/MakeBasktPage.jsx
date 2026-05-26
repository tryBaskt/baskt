import { useEffect, useMemo, useState } from "react";

import "./MakeBasktPage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const DEFAULT_START_DATE = "1960-01-01";

function formatMetricLabel(metricName) {
	return metricName
		.replace(/_/g, " ")
		.replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatMetricValue(value) {
	if (value == null || Number.isNaN(value)) {
		return "N/A";
	}

	const absoluteValue = Math.abs(value);
	if (absoluteValue >= 1_000) {
		return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
	}

	if (absoluteValue <= 1 && absoluteValue !== 0) {
		return `${(value * 100).toFixed(2)}%`;
	}

	return value.toFixed(2);
}

function buildLinePath(points, width, height, padding) {
	if (points.length === 0) {
		return "";
	}

	const minValue = Math.min(...points);
	const maxValue = Math.max(...points);
	const valueRange = maxValue - minValue || 1;
	const innerWidth = width - padding * 2;
	const innerHeight = height - padding * 2;

	return points
		.map((value, index) => {
			const x = padding + (index / Math.max(points.length - 1, 1)) * innerWidth;
			const y = padding + (1 - (value - minValue) / valueRange) * innerHeight;
			return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
		})
		.join(" ");
}

export default function MakeBasktPage() {
	const [assets, setAssets] = useState([]);
	const [isLoading, setIsLoading] = useState(true);
	const [errorMessage, setErrorMessage] = useState("");
	const [searchTerm, setSearchTerm] = useState("");
	const [savedStocks, setSavedStocks] = useState([]);
	const [backtestStartDate, setBacktestStartDate] = useState(DEFAULT_START_DATE);
	const [backtestEndDate, setBacktestEndDate] = useState(() => new Date().toISOString().slice(0, 10));
	const [backtestResult, setBacktestResult] = useState(null);
	const [backtestError, setBacktestError] = useState("");
	const [isBacktestLoading, setIsBacktestLoading] = useState(false);
	const [isFormBasktModalOpen, setIsFormBasktModalOpen] = useState(false);
	const [basktName, setBasktName] = useState("");
	const [basktDescription, setBasktDescription] = useState("");
	const [isCreatingBaskt, setIsCreatingBaskt] = useState(false);
	const [formBasktError, setFormBasktError] = useState("");

	const token = useMemo(
		() => sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "",
		[]
	);
	const totalWeight = useMemo(
		() => savedStocks.reduce((total, stock) => total + Number(stock.weightPct || 0), 0),
		[savedStocks]
	);
	const isAllocationBalanced = totalWeight === 100;
	const hasBacktestDateRange = backtestStartDate <= backtestEndDate;
	const canRunBacktest = savedStocks.length > 0 && isAllocationBalanced && hasBacktestDateRange;
	const backtestChartPath = useMemo(() => {
		const series = backtestResult?.cumulative_returns;
		return Array.isArray(series) && series.length > 0 ? buildLinePath(series, 640, 260, 16) : "";
	}, [backtestResult]);
	const latestBacktestReturn = backtestResult?.cumulative_returns?.at(-1) ?? null;

	useEffect(() => {
		let isCancelled = false;

		async function fetchAssets() {
			setIsLoading(true);
			setErrorMessage("");

			try {
				const response = await fetch(
					`${API_BASE_URL}/get_tradeable_fractionable_US_baskt_assets`,
					{
						method: "GET",
						headers: {
							...(token ? { Authorization: `Bearer ${token}` } : {}),
						},
					}
				);

				if (!response.ok) {
					throw new Error(`Failed to fetch assets (${response.status}).`);
				}

				const payload = await response.json();
				const fetchedAssets = Array.isArray(payload?.baskt_assets)
					? payload.baskt_assets
					: Array.isArray(payload?.symbols)
						? payload.symbols
						: [];

				if (!isCancelled) {
					setAssets(fetchedAssets);
				}
			} catch (error) {
				if (!isCancelled) {
					setErrorMessage(error?.message || "Unable to load tradable assets.");
					setAssets([]);
				}
			} finally {
				if (!isCancelled) {
					setIsLoading(false);
				}
			}
		}

		fetchAssets();

		return () => {
			isCancelled = true;
		};
	}, [token]);

	useEffect(() => {
		if (!canRunBacktest) {
			setBacktestResult(null);
			setIsBacktestLoading(false);
			setBacktestError(
				hasBacktestDateRange ? "" : "Start date must be on or before the end date."
			);
			return undefined;
		}

		const abortController = new AbortController();
		const positions = savedStocks.map((stock) => ({
			symbol: stock.symbol,
			weight: Number(stock.weightPct || 0) / 100,
			direction: stock.side === "short" ? -1 : 1,
			leverage: Number(stock.leverage || 1),
		}));

		async function runBacktest() {
			setIsBacktestLoading(true);
			setBacktestError("");

			try {
				const queryParams = new URLSearchParams({
					start_date: backtestStartDate,
					end_date: backtestEndDate,
					positions: JSON.stringify(positions),
				});

				const response = await fetch(`${API_BASE_URL}/backtest?${queryParams.toString()}`, {
					method: "GET",
					headers: {
						...(token ? { Authorization: `Bearer ${token}` } : {}),
					},
					signal: abortController.signal,
				});

				const payload = await response.json();
				if (!response.ok) {
					throw new Error(payload?.detail || `Backtest failed (${response.status}).`);
				}

				setBacktestResult(payload);
			} catch (error) {
				if (abortController.signal.aborted) {
					return;
				}

				setBacktestResult(null);
				setBacktestError(error?.message || "Unable to run backtest.");
			} finally {
				if (!abortController.signal.aborted) {
					setIsBacktestLoading(false);
				}
			}
		}

		runBacktest();

		return () => {
			abortController.abort();
		};
	}, [backtestEndDate, backtestStartDate, canRunBacktest, hasBacktestDateRange, savedStocks, token]);

	const normalizedSearchTerm = searchTerm.trim().toLowerCase();

	const filteredAssets = useMemo(() => {
		if (!normalizedSearchTerm) {
			return [];
		}

		return assets.filter((asset) => {
			if (typeof asset === "string") {
				return asset.toLowerCase().includes(normalizedSearchTerm);
			}

			const symbol = String(asset?.symbol || "").toLowerCase();
			return symbol.includes(normalizedSearchTerm);
		});
	}, [assets, normalizedSearchTerm]);

	function onSelectSymbol(symbol) {
		setSavedStocks((currentStocks) => {
			if (currentStocks.some((stock) => stock.symbol === symbol)) {
				return currentStocks;
			}

			const existingWeightTotal = currentStocks.reduce(
				(total, stock) => total + Number(stock.weightPct || 0),
				0
			);
			const remainingWeight = Math.max(0, 100 - existingWeightTotal);

			return [
				...currentStocks,
				{ symbol, side: "long", weightPct: Math.floor(remainingWeight), leverage: 1 },
			];
		});
	}

	function onRemoveSymbol(symbol) {
		setSavedStocks((currentStocks) =>
			currentStocks.filter((stock) => stock.symbol !== symbol)
		);
	}

	function onSetStockSide(symbol, side) {
		setSavedStocks((currentStocks) =>
			currentStocks.map((stock) =>
				stock.symbol === symbol ? { ...stock, side } : stock
			)
		);
	}

	function onSetStockWeight(symbol, nextWeight) {
		const parsedWeight = Number.parseInt(nextWeight, 10);
		const safeWeight = Number.isFinite(parsedWeight)
			? Math.min(100, Math.max(0, parsedWeight))
			: 0;

		setSavedStocks((currentStocks) =>
			currentStocks.map((stock) =>
				stock.symbol === symbol ? { ...stock, weightPct: safeWeight } : stock
			)
		);
	}

	async function onConfirmFormBaskt() {
		setFormBasktError("");

		if (!basktName.trim()) {
			setFormBasktError("Please enter a Baskt name.");
			return;
		}

		if (savedStocks.length === 0) {
			setFormBasktError("Add at least one stock before forming your Baskt.");
			return;
		}

		const payload = {
			name: basktName.trim(),
			description: basktDescription.trim() || null,
			positions: savedStocks.map((stock) => ({
				symbol: stock.symbol,
				target_weight: Number(stock.weightPct || 0),
				direction: stock.side === "short" ? -1 : 1,
				leverage: Number(stock.leverage || 1),
			})),
		};

		try {
			setIsCreatingBaskt(true);
			const response = await fetch(`${API_BASE_URL}/portfolios`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					...(token ? { Authorization: `Bearer ${token}` } : {}),
				},
				body: JSON.stringify(payload),
			});

			const result = await response.json().catch(() => ({}));
			if (!response.ok) {
				throw new Error(result?.detail || `Failed to create Baskt (${response.status}).`);
			}

			setIsFormBasktModalOpen(false);
			setBasktName("");
			setBasktDescription("");
		} catch (error) {
			setFormBasktError(error?.message || "Unable to create Baskt.");
		} finally {
			setIsCreatingBaskt(false);
		}
	}

	return (
		<section className="make-baskt-page" aria-labelledby="make-baskt-title">
			<h1 id="make-baskt-title">Make a Baskt</h1>
			<div className="make-baskt-body">
				<section className="search-stocks-box" aria-labelledby="search-stocks-title">
					<div className="search-stocks-box-heading">
						<h2 id="search-stocks-title">Search Stocks</h2>
					</div>
					<input
						id="asset-search"
						type="text"
						value={searchTerm}
						onChange={(event) => setSearchTerm(event.target.value)}
						placeholder="Type a symbol (e.g. AAPL)"
						className="make-baskt-search-input"
						autoComplete="off"
					/>
					{isLoading ? <p className="make-baskt-meta">Loading assets...</p> : null}
					{errorMessage ? <p className="make-baskt-error">{errorMessage}</p> : null}
					{!isLoading && !errorMessage && normalizedSearchTerm ? (
						<span className="search-count-badge">{filteredAssets.length} matching stocks</span>
					) : null}

					{!isLoading && !errorMessage && normalizedSearchTerm ? (
						<div className="assets-list" role="list" aria-label="Available assets">
							{filteredAssets.map((asset) => {
								const symbol = typeof asset === "string" ? asset : asset.symbol;
								const isSaved = savedStocks.some((stock) => stock.symbol === symbol);
								return (
									<button
										type="button"
										className={`asset-item${isSaved ? " is-saved" : ""}`}
										key={symbol}
										role="listitem"
										onClick={() => onSelectSymbol(symbol)}
									>
										<strong>{symbol}</strong>
									</button>
								);
							})}
						</div>
					) : null}
				</section>

				<section className="new-baskt-box" aria-labelledby="saved-stocks-title">
					<div className="saved-stocks-box-heading">
						<h2 id="saved-stocks-title">New Baskt</h2>
						<span className={`total-weight-badge${totalWeight === 100 ? " is-balanced" : totalWeight > 100 ? " is-over" : ""}`}>Total weight: {totalWeight}%</span>
					</div>
					{savedStocks.length === 0 ? (
						<p className="baskt-empty-state">Click a stock to add it here.</p>
					) : (
						<>
							<div className="saved-stocks-header" aria-hidden="true">
								<span>Symbol</span>
								<span>Direction</span>
								<span>Weight</span>
								<span>Leverage</span>
								<span className="saved-stocks-header-remove" />
							</div>
							<div className="saved-stocks-list" role="list" aria-label="New Baskt stocks">
								{savedStocks.map((stock) => (
									<div className="saved-stock-item" key={stock.symbol} role="listitem">
										<strong>{stock.symbol}</strong>
										<div className="side-toggle" role="group" aria-label={`Position side for ${stock.symbol}`}>
											<button
												type="button"
												className={stock.side === "long" ? "is-selected" : ""}
												onClick={() => onSetStockSide(stock.symbol, "long")}
											>
												L
											</button>
											<button
												type="button"
												className={stock.side === "short" ? "is-selected" : ""}
												onClick={() => onSetStockSide(stock.symbol, "short")}
											>
												S
											</button>
										</div>
										<div className="weight-input-wrap">
											<input
												type="number"
												min="0"
												max="100"
												step="1"
												inputMode="numeric"
												value={stock.weightPct ?? 0}
												aria-label={`Weight for ${stock.symbol}`}
												onChange={(event) => onSetStockWeight(stock.symbol, event.target.value)}
											/>
											<span className="weight-suffix">%</span>
										</div>
										<div className="leverage-input-wrap">
											<input
												type="number"
												value={stock.leverage ?? 1}
												readOnly
												aria-label={`Leverage for ${stock.symbol}`}
											/>
										</div>
										<button
											type="button"
											className="remove-stock-button"
											aria-label={`Remove ${stock.symbol}`}
											onClick={() => onRemoveSymbol(stock.symbol)}
										>
											X
										</button>
									</div>
								))}
							</div>
						</>
					)}
					{savedStocks.length > 0 && !isAllocationBalanced ? (
						<p className="baskt-info-banner">Backtest runs automatically once total weight reaches 100%.</p>
					) : null}
				</section>

				<section className="backtest-box" aria-labelledby="backtest-title">
						<div className="backtest-box-heading">
							<h2 id="backtest-title">Backtest</h2>
						</div>
						<div className="backtest-date-grid">
							<label>
								<span>Start date</span>
								<input
									type="date"
									value={backtestStartDate}
									onChange={(event) => setBacktestStartDate(event.target.value)}
								/>
							</label>
							<label>
								<span>End date</span>
								<input
									type="date"
									value={backtestEndDate}
									onChange={(event) => setBacktestEndDate(event.target.value)}
								/>
							</label>
						</div>

						{isBacktestLoading ? <p className="backtest-loading">Running backtest...</p> : null}
						{backtestError ? <p className="make-baskt-error">{backtestError}</p> : null}
						{!backtestError && !isBacktestLoading && !canRunBacktest ? (
							<p className="make-baskt-meta">Set a valid date range and a 100% basket to run the backtest.</p>
						) : null}

						{backtestResult ? (
							<>
								<div className="backtest-chart-card">
									<div className="backtest-chart-header">
										<p>Cumulative return</p>
										<span>{backtestResult.dates?.[0]} to {backtestResult.dates?.at(-1)}</span>
									</div>
									<svg viewBox="0 0 640 260" className="backtest-chart" role="img" aria-label="Backtest cumulative return chart">
										<path d={backtestChartPath} className="backtest-chart-line" />
									</svg>
								</div>
								<div className="backtest-metrics-grid">
									{Object.entries(backtestResult.metrics || {}).map(([metricName, metricValue]) => (
										<div className="backtest-metric-card" key={metricName}>
											<p>{formatMetricLabel(metricName)}</p>
											<strong>{formatMetricValue(metricValue)}</strong>
										</div>
									))}
								</div>
							</>
						) : null}					<button
						type="button"
						className="form-baskt-button"
						onClick={() => setIsFormBasktModalOpen(true)}
					>
						Form Baskt
					</button>
				</section>
			</div>
			{isFormBasktModalOpen ? (
				<div
					className="form-baskt-overlay"
					role="dialog"
					aria-modal="true"
					aria-labelledby="form-baskt-title"
					onClick={() => setIsFormBasktModalOpen(false)}
				>
					<div className="form-baskt-modal" onClick={(event) => event.stopPropagation()}>
						<h3 id="form-baskt-title">Form Baskt</h3>
						{formBasktError ? <p className="make-baskt-error">{formBasktError}</p> : null}
						<label htmlFor="baskt-name">
							<span>Baskt name</span>
							<input
								id="baskt-name"
								type="text"
								value={basktName}
								onChange={(event) => setBasktName(event.target.value)}
								placeholder="e.g. Tech Growth"
							/>
							<small className="baskt-name-note">you can't change this later</small>
						</label>
						<label htmlFor="baskt-description">
							<span>Description</span>
							<textarea
								id="baskt-description"
								value={basktDescription}
								onChange={(event) => setBasktDescription(event.target.value)}
								placeholder="Describe your baskt strategy..."
								rows={4}
							/>
						</label>
						<div className="form-baskt-modal-actions">
							<button
								type="button"
								className="form-baskt-cancel"
								disabled={isCreatingBaskt}
								onClick={() => setIsFormBasktModalOpen(false)}
							>
								Cancel
							</button>
							<button
								type="button"
								className="form-baskt-confirm"
								disabled={isCreatingBaskt}
								onClick={onConfirmFormBaskt}
							>
								{isCreatingBaskt ? "Creating..." : "Confirm"}
							</button>
						</div>
					</div>
				</div>
			) : null}
		</section>
	);
}
