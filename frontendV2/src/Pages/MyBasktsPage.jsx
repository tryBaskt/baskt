import { useEffect, useMemo, useState } from "react";

import "./MyBasktsPage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function normalizePortfolios(payload) {
	if (Array.isArray(payload)) {
		return payload;
	}
	if (Array.isArray(payload?.portfolios)) {
		return payload.portfolios;
	}
	if (Array.isArray(payload?.items)) {
		return payload.items;
	}
	return [];
}

export default function MyBasktsPage({ onOpenBaskt }) {
	const [portfolios, setPortfolios] = useState([]);
	const [isLoading, setIsLoading] = useState(true);
	const [errorMessage, setErrorMessage] = useState("");

	const token = useMemo(
		() => sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "",
		[]
	);

	useEffect(() => {
		let isCancelled = false;

		async function fetchPortfolios() {
			setIsLoading(true);
			setErrorMessage("");

			try {
				const response = await fetch(`${API_BASE_URL}/model-portfolios`, {
					method: "GET",
					headers: {
						...(token ? { Authorization: `Bearer ${token}` } : {}),
					},
				});

				const payload = await response.json().catch(() => ({}));
				if (!response.ok) {
					throw new Error(payload?.detail || `Failed to load portfolios (${response.status}).`);
				}

				const allPortfolios = normalizePortfolios(payload);

				if (!isCancelled) {
					setPortfolios(allPortfolios);
				}
			} catch (error) {
				if (!isCancelled) {
					setErrorMessage(error?.message || "Unable to load your Baskts.");
					setPortfolios([]);
				}
			} finally {
				if (!isCancelled) {
					setIsLoading(false);
				}
			}
		}

		fetchPortfolios();

		return () => {
			isCancelled = true;
		};
	}, [token]);

	return (
		<section className="my-baskts-page" aria-labelledby="my-baskts-title">
			<div className="my-baskts-header">
				<h1 id="my-baskts-title">My Baskts</h1>
				<span className="my-baskts-count">{portfolios.length} total</span>
			</div>

			{isLoading ? <p className="my-baskts-meta">Loading your portfolios...</p> : null}
			{errorMessage ? <p className="my-baskts-error">{errorMessage}</p> : null}

			{!isLoading && !errorMessage && portfolios.length === 0 ? (
				<p className="my-baskts-empty">No Baskts yet.</p>
			) : null}

			{!isLoading && !errorMessage && portfolios.length > 0 ? (
				<div className="my-baskts-grid" role="list" aria-label="Your portfolios">
					{portfolios.map((portfolio, index) => {
						const portfolioId = portfolio?.portfolio_id || `portfolio-${index}`;
						const portfolioName = portfolio?.portfolio_name || "Untitled Baskt";
						const description = portfolio?.description;

						return (
							<button
								type="button"
								className="my-baskts-card"
								key={portfolioId}
								role="listitem"
								onClick={() => {
									if (onOpenBaskt) {
										onOpenBaskt({
											portfolioId,
											portfolioName,
											description: description || "",
										});
									}
								}}
							>
								<h2>{portfolioName}</h2>
								{description ? <p>{description}</p> : <p className="my-baskts-description-empty">No description</p>}
							</button>
						);
					})}
				</div>
			) : null}
		</section>
	);
}
