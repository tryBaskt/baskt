import { useEffect, useMemo, useState } from "react";

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

	return `${(numericWeight * 100).toFixed(2)}%`;
}

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
				setErrorMessage("No Baskt selected.");
				setIsLoading(false);
				return;
			}

			setIsLoading(true);
			setErrorMessage("");

			try {
				const response = await fetch(`${API_BASE_URL}/model-portfolios/${selectedBaskt.portfolioId}`, {
					method: "GET",
					headers: {
						...(token ? { Authorization: `Bearer ${token}` } : {}),
					},
				});

				const payload = await response.json().catch(() => ({}));
				if (!response.ok) {
					throw new Error(payload?.detail || `Failed to load baskt details (${response.status}).`);
				}

				const history = Array.isArray(payload?.position_history) ? payload.position_history : [];
				const latestSnapshot = history.length > 0 ? history[history.length - 1] : null;
				const latestPositions = buildPositionsFromCurrentWeight(
					payload?.positions_current_weight,
					latestSnapshot?.positions
				);

				if (!isCancelled) {
					setDetails({
						portfolioOwnerCognitoUserId: payload?.portfolio_owner_cognito_user_id || "",
						portfolioName: payload?.portfolio_name || selectedBaskt?.portfolioName || "Untitled Baskt",
						description: payload?.description ?? selectedBaskt?.description ?? "",
						createdAt: payload?.created_at,
						updatedAt: payload?.updated_at,
						latestPositions,
					});
				}
			} catch (error) {
				if (!isCancelled) {
					setErrorMessage(error?.message || "Unable to load baskt details.");
					setDetails(null);
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
					</header>

					<div className="baskt-dates">
						<p>
							<strong>Created:</strong> {formatDate(details.createdAt)}
						</p>
						<p>
							<strong>Last updated:</strong> {formatDate(details.updatedAt)}
						</p>
					</div>

					<div className="baskt-positions">
						<h2>Latest Portfolio Positions</h2>

						{details.latestPositions.length === 0 ? (
							<p className="baskt-meta">No positions available.</p>
						) : (
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
										{details.latestPositions.map((position, index) => (
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
						)}
					</div>
				</>
			) : null}
		</section>
	);
}
