import { useEffect, useMemo, useState } from "react";

import AccountEquityGraph from "../components/AccountEquityGraph";
import "./HomePage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export default function HomePage() {
  const [performanceByPeriod, setPerformanceByPeriod] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const token = useMemo(
    () => sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "",
    []
  );

  useEffect(() => {
    let isCancelled = false;

    async function fetchAccountPerformance() {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const response = await fetch(`${API_BASE_URL}/account-performance/account-id`, {
          method: "GET",
          headers: {
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload?.detail || `Failed to load account performance (${response.status}).`);
        }

        if (!isCancelled) {
          setPerformanceByPeriod(payload && typeof payload === "object" ? payload : {});
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(error?.message || "Unable to load account performance.");
          setPerformanceByPeriod({});
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    fetchAccountPerformance();

    return () => {
      isCancelled = true;
    };
  }, [token]);

  return (
    <section className="account-performance-page" aria-labelledby="home-title">
      <AccountEquityGraph
        performanceByPeriod={performanceByPeriod}
        isLoading={isLoading}
        errorMessage={errorMessage}
      />
    </section>
  );
}
