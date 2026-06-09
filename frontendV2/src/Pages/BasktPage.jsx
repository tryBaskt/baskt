import { useEffect, useMemo, useState } from "react";

import AccountEquityGraph from "../components/AccountEquityGraph";
import "./BasktPage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function formatDate(value) {
	if (!value) {
		return "-";
	}

	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return "-";
	}

	return date.toLocaleString();
}

function formatWeightPercentage(value) {
	const numericWeight = Number(value);
	if (!Number.isFinite(numericWeight)) {
		return "-";
	}

	const percentageValue = Math.abs(numericWeight) > 1 ? numericWeight : numericWeight * 100;
	return `${percentageValue.toFixed(2)}%`;
}

function formatPercentValue(value) {
	const numericValue = Number(value);
	if (!Number.isFinite(numericValue)) {
		return "-";
	}

	return `${numericValue.toFixed(2)}%`;
}

function formatCurrency(value) {
	const numericValue = Number(value);
	if (!Number.isFinite(numericValue)) {
		return "-";
	}

	return new Intl.NumberFormat("en-US", {
		style: "currency",
		currency: "USD",
		maximumFractionDigits: 2,
	}).format(numericValue);
}

const modelPortfolioMetricDefinitions = [
	{
		label: "Total Return",
		key: "total_cumulative_return",
		format: "percentageValue",
		signed: true,
	},
	{
		label: "CAGR",
		key: "cagr",
		format: "percentageValue",
		signed: true,
	},
	{
		label: "Ann. Volatility",
		key: "annualized_volatility",
		format: "percentageValue",
	},
	{
		label: "Leverage Direction",
		key: "leverage_adjusted_direction",
		format: "number",
		signed: true,
	},
];

function normalizePosition(position) {
	return {
		symbol: position?.symbol || "-",
		direction: position?.direction ?? "-",
		weight: position?.weight ?? position?.target_weight ?? "-",
		leverage: position?.leverage ?? "-",
	};
}

function buildPositionsFromCurrentWeight(currentWeightBySymbol, snapshotPositions) {
	if (!currentWeightBySymbol || typeof currentWeightBySymbol !== "object") {
		return [];
	}

	const snapshotBySymbol = new Map(
		(Array.isArray(snapshotPositions) ? snapshotPositions : []).map((position) => [position?.symbol, position])
	);

	return Object.entries(currentWeightBySymbol).map(([symbol, weight]) => {
		const snapshotPosition = snapshotBySymbol.get(symbol);
		return normalizePosition({
			symbol,
			weight,
			direction: snapshotPosition?.direction,
			leverage: snapshotPosition?.leverage,
		});
	});
}

function getJwtPayload(token) {
	if (!token) {
		return {};
	}

	try {
		const [, payload] = token.split(".");
		const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
		const paddedPayload = normalizedPayload.padEnd(
			normalizedPayload.length + ((4 - (normalizedPayload.length % 4)) % 4),
			"="
		);
		const decodedPayload = window.atob(paddedPayload);
		return JSON.parse(decodedPayload);
	} catch {
		return {};
	}
}

export default function BasktPage({ selectedBaskt, onBack, onUpdateBaskt }) {
	const [isLoading, setIsLoading] = useState(true);
	const [errorMessage, setErrorMessage] = useState("");
	const [details, setDetails] = useState(null);
	const [performanceByPeriod, setPerformanceByPeriod] = useState({});
	const [isPerformanceLoading, setIsPerformanceLoading] = useState(true);
	const [performanceErrorMessage, setPerformanceErrorMessage] = useState("");
	const [selectedPreviousSnapshotIndex, setSelectedPreviousSnapshotIndex] = useState("");
	const [investedAmount, setInvestedAmount] = useState(0);
	const [isInvestmentLoading, setIsInvestmentLoading] = useState(true);
	const [tradeModalType, setTradeModalType] = useState(null);
	const [tradeAmount, setTradeAmount] = useState("");
	const [sellMode, setSellMode] = useState("amount");
	const [tradeErrorMessage, setTradeErrorMessage] = useState("");
	const [tradeStatusMessage, setTradeStatusMessage] = useState("");
	const [isTradeSubmitting, setIsTradeSubmitting] = useState(false);

	const token = useMemo(
		() => sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "",
		[]
	);
	const currentUserSub = useMemo(() => getJwtPayload(token)?.sub || "", [token]);

	useEffect(() => {
		let isCancelled = false;

		async function fetchPortfolioDetails() {
			if (!selectedBaskt?.portfolioId) {
				setDetails(null);
				setPerformanceByPeriod({});
				setErrorMessage("No Baskt selected.");
				setIsLoading(false);
				setIsPerformanceLoading(false);
				setIsInvestmentLoading(false);
				return;
			}

			setIsLoading(true);
			setIsPerformanceLoading(true);
			setErrorMessage("");
			setPerformanceErrorMessage("");
			setPerformanceByPeriod({});
			setSelectedPreviousSnapshotIndex("");
			setInvestedAmount(0);
			setIsInvestmentLoading(true);
			setTradeStatusMessage("");
			setTradeErrorMessage("");

			try {
				const detailsRequest = fetch(`${API_BASE_URL}/model-portfolios/${selectedBaskt.portfolioId}`, {
					method: "GET",
					headers: {
						...(token ? { Authorization: `Bearer ${token}` } : {}),
					},
				}).then(async (response) => {
					const payload = await response.json().catch(() => ({}));
					if (!response.ok) {
						throw new Error(payload?.detail || `Failed to load baskt details (${response.status}).`);
					}
					return payload;
				});

				const performanceRequest = fetch(
					`${API_BASE_URL}/model-portfolios/${selectedBaskt.portfolioId}/performance`,
					{
						method: "GET",
						headers: {
							...(token ? { Authorization: `Bearer ${token}` } : {}),
						},
					}
				).then(async (response) => {
					const payload = await response.json().catch(() => ({}));
					if (!response.ok) {
						throw new Error(payload?.detail || `Failed to load baskt performance (${response.status}).`);
					}
					return payload;
				});

				const investmentRequest = fetch(
					`${API_BASE_URL}/trade-execution/portfolios/${selectedBaskt.portfolioId}/investment`,
					{
						method: "GET",
						headers: {
							...(token ? { Authorization: `Bearer ${token}` } : {}),
						},
					}
				).then(async (response) => {
					const payload = await response.json().catch(() => ({}));
					if (!response.ok) {
						throw new Error(payload?.detail || `Failed to load invested amount (${response.status}).`);
					}
					return payload;
				});

				const handledPerformanceRequest = performanceRequest
					.then((performancePayload) => {
						if (!isCancelled) {
							setPerformanceByPeriod(
								performancePayload && typeof performancePayload === "object"
									? performancePayload
									: {}
							);
						}
					})
					.catch((error) => {
						if (!isCancelled) {
							setPerformanceErrorMessage(error?.message || "Unable to load baskt performance.");
							setPerformanceByPeriod({});
						}
					})
					.finally(() => {
						if (!isCancelled) {
							setIsPerformanceLoading(false);
						}
					});
				void handledPerformanceRequest;

				const handledInvestmentRequest = investmentRequest
					.then((investmentPayload) => {
						if (!isCancelled) {
							const nextInvestedAmount = Number(investmentPayload?.invested_amount);
							setInvestedAmount(Number.isFinite(nextInvestedAmount) ? nextInvestedAmount : 0);
						}
					})
					.catch(() => {
						if (!isCancelled) {
							setInvestedAmount(0);
						}
					})
					.finally(() => {
						if (!isCancelled) {
							setIsInvestmentLoading(false);
						}
					});
				void handledInvestmentRequest;

				const payload = await detailsRequest;

				const history = Array.isArray(payload?.position_history) ? payload.position_history : [];
				const latestSnapshot = history.length > 0 ? history[history.length - 1] : null;
				const latestPositions = buildPositionsFromCurrentWeight(
					payload?.positions_current_weight,
					latestSnapshot?.positions
				);
				const previousSnapshots = history
					.slice(0, -1)
					.reverse()
					.map((snapshot) => ({
						timestamp: snapshot?.timestamp,
						positions: Array.isArray(snapshot?.positions)
							? snapshot.positions.map((position) => normalizePosition(position))
							: [],
					}));

				if (!isCancelled) {
					setDetails({
						portfolioOwnerCognitoUserId: payload?.portfolio_owner_cognito_user_id || "",
						portfolioName: payload?.portfolio_name || selectedBaskt?.portfolioName || "Untitled Baskt",
						description: payload?.description ?? selectedBaskt?.description ?? "",
						createdAt: payload?.created_at,
						updatedAt: payload?.updated_at,
						latestPositions,
						previousSnapshots,
					});
				}
			} catch (error) {
				if (!isCancelled) {
					setErrorMessage(error?.message || "Unable to load baskt details.");
					setDetails(null);
					setIsPerformanceLoading(false);
					setIsInvestmentLoading(false);
				}
			} finally {
				if (!isCancelled) {
					setIsLoading(false);
				}
			}
		}

		fetchPortfolioDetails();

		return () => {
			isCancelled = true;
		};
	}, [selectedBaskt, token]);

	function openTradeModal(type) {
		setTradeModalType(type);
		setTradeAmount("");
		setSellMode("amount");
		setTradeErrorMessage("");
		setTradeStatusMessage("");
	}

	function closeTradeModal() {
		if (isTradeSubmitting) {
			return;
		}

		setTradeModalType(null);
		setTradeAmount("");
		setSellMode("amount");
		setTradeErrorMessage("");
	}

	async function refreshInvestedAmount() {
		if (!selectedBaskt?.portfolioId) {
			return;
		}

		try {
			setIsInvestmentLoading(true);
			const response = await fetch(
				`${API_BASE_URL}/trade-execution/portfolios/${selectedBaskt.portfolioId}/investment`,
				{
					method: "GET",
					headers: {
						...(token ? { Authorization: `Bearer ${token}` } : {}),
					},
				}
			);
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) {
				throw new Error(payload?.detail || "Failed to refresh invested amount.");
			}
			const nextInvestedAmount = Number(payload?.invested_amount);
			setInvestedAmount(Number.isFinite(nextInvestedAmount) ? nextInvestedAmount : 0);
		} catch {
			setInvestedAmount(0);
		} finally {
			setIsInvestmentLoading(false);
		}
	}

	async function submitTrade() {
		if (!selectedBaskt?.portfolioId || !details?.portfolioOwnerCognitoUserId) {
			setTradeErrorMessage("Unable to submit trade for this Baskt.");
			return;
		}

		const numericAmount = Number(tradeAmount);
		const isSellAll = tradeModalType === "sell" && sellMode === "all";

		if (!isSellAll && (!Number.isFinite(numericAmount) || numericAmount <= 0)) {
			setTradeErrorMessage("Enter an amount greater than 0.");
			return;
		}

		if (tradeModalType === "sell" && sellMode === "amount" && numericAmount > investedAmount) {
			setTradeErrorMessage(`Sell amount cannot exceed ${formatCurrency(investedAmount)}.`);
			return;
		}

		setIsTradeSubmitting(true);
		setTradeErrorMessage("");
		setTradeStatusMessage("");

		try {
			const endpoint =
				tradeModalType === "invest"
					? `${API_BASE_URL}/trade-execution/portfolios/${selectedBaskt.portfolioId}/deposits`
					: isSellAll
						? `${API_BASE_URL}/trade-execution/portfolios/${selectedBaskt.portfolioId}/sell-all`
						: `${API_BASE_URL}/trade-execution/portfolios/${selectedBaskt.portfolioId}/withdrawals`;
			const body = isSellAll
				? { portfolio_owner_cognito_user_id: details.portfolioOwnerCognitoUserId }
				: {
					portfolio_owner_cognito_user_id: details.portfolioOwnerCognitoUserId,
					amount: numericAmount,
				};

			const response = await fetch(endpoint, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					...(token ? { Authorization: `Bearer ${token}` } : {}),
				},
				body: JSON.stringify(body),
			});
			const payload = await response.json().catch(() => ({}));
			if (!response.ok) {
				throw new Error(payload?.detail || `Failed to ${tradeModalType === "invest" ? "invest" : "sell"}.`);
			}

			setTradeStatusMessage(tradeModalType === "invest" ? "Investment submitted." : "Sell order submitted.");
			setTradeModalType(null);
			setTradeAmount("");
			await refreshInvestedAmount();
		} catch (error) {
			setTradeErrorMessage(error?.message || "Trade submission failed.");
		} finally {
			setIsTradeSubmitting(false);
		}
	}

	return (
		<section className="baskt-page" aria-labelledby="baskt-title">
			{isLoading ? <p className="baskt-meta">Loading baskt details...</p> : null}
			{errorMessage ? <p className="baskt-error">{errorMessage}</p> : null}

			{!isLoading && !errorMessage && details ? (
				<>
					<header className="baskt-header">
						<div>
							<h1 id="baskt-title">{details.portfolioName}</h1>
							<p className="baskt-description">{details.description || "No description"}</p>
						</div>
						<div className="baskt-actions">
							<div className="baskt-invested-summary">
								<span>Invested</span>
								<strong>{isInvestmentLoading ? "Loading..." : formatCurrency(investedAmount)}</strong>
							</div>
							<button type="button" className="baskt-trade-button" onClick={() => openTradeModal("invest")}>
								Invest
							</button>
							<button
								type="button"
								className="baskt-trade-button is-secondary"
								onClick={() => openTradeModal("sell")}
								disabled={isInvestmentLoading || investedAmount <= 0}
							>
								Sell
							</button>
							{details.portfolioOwnerCognitoUserId && details.portfolioOwnerCognitoUserId === currentUserSub ? (
								<button
									type="button"
									className="baskt-update-button"
									onClick={() => {
										if (onUpdateBaskt) {
											onUpdateBaskt({
												portfolioId: selectedBaskt?.portfolioId,
												...details,
											});
										}
									}}
								>
									Update
								</button>
							) : null}
						</div>
					</header>

					{tradeStatusMessage ? <p className="baskt-success">{tradeStatusMessage}</p> : null}

					<div className="baskt-main-grid">
						<div className="baskt-performance">
							<AccountEquityGraph
								performanceByPeriod={performanceByPeriod}
								isLoading={isPerformanceLoading}
								errorMessage={performanceErrorMessage}
								title="Baskt Performance"
								ariaLabel="Baskt cumulative returns over time"
								valueKey="cumulative_returns"
								latestValueFormatter={formatPercentValue}
								emptyMessage="No Baskt performance history available."
								loadingMessage="Loading Baskt performance..."
								metricDefinitions={modelPortfolioMetricDefinitions}
							/>
						</div>

						<div className="baskt-positions-panel">
							<div className="baskt-positions">
								<h2>Latest Portfolio Positions</h2>

								{details.latestPositions.length === 0 ? (
									<p className="baskt-meta">No positions available.</p>
								) : (
									<PositionsTable positions={details.latestPositions} />
								)}
							</div>

							{details.previousSnapshots.length > 0 ? (
								<div className="baskt-previous-positions">
									<label htmlFor="previous-snapshot-select">Previous positions</label>
									<select
										id="previous-snapshot-select"
										value={selectedPreviousSnapshotIndex}
										onChange={(event) => setSelectedPreviousSnapshotIndex(event.target.value)}
									>
										<option value="">Select a previous snapshot</option>
										{details.previousSnapshots.map((snapshot, index) => (
											<option key={`${snapshot.timestamp}-${index}`} value={String(index)}>
												{formatDate(snapshot.timestamp)}
											</option>
										))}
									</select>

									{selectedPreviousSnapshotIndex !== "" ? (
										<PositionsTable
											positions={
												details.previousSnapshots[Number(selectedPreviousSnapshotIndex)]
													?.positions || []
											}
										/>
									) : null}
								</div>
							) : null}
						</div>
					</div>
				</>
			) : null}

			{tradeModalType ? (
				<div className="baskt-modal-backdrop" role="presentation" onMouseDown={closeTradeModal}>
					<div
						className="baskt-trade-modal"
						role="dialog"
						aria-modal="true"
						aria-labelledby="baskt-trade-modal-title"
						onMouseDown={(event) => event.stopPropagation()}
					>
						<div>
							<p className="baskt-modal-eyebrow">{tradeModalType === "invest" ? "Invest" : "Sell"}</p>
							<h2 id="baskt-trade-modal-title">
								{tradeModalType === "invest" ? "Invest in Baskt" : "Sell from Baskt"}
							</h2>
						</div>

						{tradeModalType === "sell" ? (
							<div className="baskt-sell-mode" role="radiogroup" aria-label="Sell mode">
								<label>
									<input
										type="radio"
										name="sell-mode"
										value="amount"
										checked={sellMode === "amount"}
										onChange={() => setSellMode("amount")}
									/>
									Specific amount
								</label>
								<label>
									<input
										type="radio"
										name="sell-mode"
										value="all"
										checked={sellMode === "all"}
										onChange={() => setSellMode("all")}
									/>
									Sell all
								</label>
							</div>
						) : null}

						{tradeModalType === "invest" || sellMode === "amount" ? (
							<label className="baskt-trade-field">
								<span>Amount</span>
								<input
									type="number"
									min="0"
									step="0.01"
									max={tradeModalType === "sell" ? investedAmount : undefined}
									value={tradeAmount}
									onChange={(event) => setTradeAmount(event.target.value)}
									placeholder="0.00"
								/>
							</label>
						) : null}

						{tradeModalType === "sell" ? (
							<p className="baskt-modal-note">
								Available to sell: <strong>{formatCurrency(investedAmount)}</strong>
							</p>
						) : null}

						{tradeErrorMessage ? <p className="baskt-error">{tradeErrorMessage}</p> : null}

						<div className="baskt-modal-actions">
							<button type="button" className="baskt-modal-cancel" onClick={closeTradeModal}>
								Cancel
							</button>
							<button
								type="button"
								className="baskt-modal-submit"
								onClick={submitTrade}
								disabled={
									isTradeSubmitting
									|| (tradeModalType === "sell" && sellMode === "amount" && investedAmount <= 0)
									|| (tradeModalType === "sell" && sellMode === "amount" && Number(tradeAmount) > investedAmount)
								}
							>
								{isTradeSubmitting ? "Submitting..." : tradeModalType === "invest" ? "Invest" : "Sell"}
							</button>
						</div>
					</div>
				</div>
			) : null}
		</section>
	);
}

function PositionsTable({ positions }) {
	return (
		<div className="baskt-table-wrap">
			<table>
				<thead>
					<tr>
						<th>Symbol</th>
						<th>Direction</th>
						<th>Weight</th>
						<th>Leverage</th>
					</tr>
				</thead>
				<tbody>
					{positions.map((position, index) => (
						<tr key={`${position.symbol}-${index}`}>
							<td>{position.symbol}</td>
							<td>{position.direction}</td>
							<td>{formatWeightPercentage(position.weight)}</td>
							<td>{position.leverage}</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}
