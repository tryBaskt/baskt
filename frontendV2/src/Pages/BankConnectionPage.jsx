import { useCallback, useEffect, useState } from "react";

import "./BankConnectionPage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const defaultBankRelationship = {
  account_owner_name: "",
  bank_account_type: "CHECKING",
  bank_account_number: "",
  bank_routing_number: "",
  nickname: "",
};

const bankAccountTypeOptions = [
  { value: "CHECKING", label: "Checking" },
  { value: "SAVINGS", label: "Savings" },
  { value: "", label: "None" },
];

function responseValue(response, key) {
  if (!response || typeof response !== "object") {
    return null;
  }
  return response[key] ?? null;
}

export default function BankConnectionPage() {
  const [bankRelationship, setBankRelationship] = useState(defaultBankRelationship);
  const [achRelationships, setAchRelationships] = useState([]);
  const [isLoadingRelationships, setIsLoadingRelationships] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [validationError, setValidationError] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [createdRelationship, setCreatedRelationship] = useState(null);

  function updateBankRelationship(fieldName, value) {
    setBankRelationship((currentBankRelationship) => ({
      ...currentBankRelationship,
      [fieldName]: value,
    }));
  }

  const fetchAchRelationships = useCallback(async () => {
    setIsLoadingRelationships(true);
    setErrorMessage("");

    try {
      const token = sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "";
      const response = await fetch(`${API_BASE_URL}/accounts/ach-relationships`, {
        method: "GET",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });

      const responsePayload = await response.json().catch(() => []);
      if (!response.ok) {
        throw new Error(responsePayload?.detail || `Failed to load bank relationships (${response.status}).`);
      }

      setAchRelationships(Array.isArray(responsePayload) ? responsePayload : []);
    } catch (error) {
      setErrorMessage(error?.message || "Failed to load bank relationships.");
      setAchRelationships([]);
    } finally {
      setIsLoadingRelationships(false);
    }
  }, []);

  useEffect(() => {
    fetchAchRelationships();
  }, [fetchAchRelationships]);

  async function handleBankRelationshipSubmit(event) {
    event.preventDefault();
    setValidationError("");
    setErrorMessage("");
    setSuccessMessage("");
    setCreatedRelationship(null);

    const payload = {
      bank_account_owner_name: bankRelationship.account_owner_name.trim(),
      bank_account_type: bankRelationship.bank_account_type,
      bank_account_number: bankRelationship.bank_account_number.trim(),
      bank_account_routing_number: bankRelationship.bank_routing_number.trim(),
      bank_account_nickname: bankRelationship.nickname.trim() || undefined,
    };

    if (!payload.bank_account_owner_name || !payload.bank_account_number || !payload.bank_account_routing_number) {
      setValidationError("Please fill out every required bank field.");
      return;
    }

    try {
      setIsSubmitting(true);
      const token = sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "";
      const response = await fetch(`${API_BASE_URL}/accounts/create-ach-relationships`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
      });

      const responsePayload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(responsePayload?.detail || `Failed to connect bank (${response.status}).`);
      }

      setCreatedRelationship(responsePayload);
      setSuccessMessage("Bank relationship created successfully.");
      setBankRelationship(defaultBankRelationship);
      fetchAchRelationships();
    } catch (error) {
      setErrorMessage(error?.message || "Failed to connect bank.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="bank-connection-page" aria-labelledby="bank-connection-title">
      <div className="bank-connection-panel">
        <header className="bank-connection-header">
          <h1 id="bank-connection-title">Connect to your Bank</h1>
        </header>

        {successMessage ? <p className="bank-connection-success">{successMessage}</p> : null}
        {errorMessage ? <p className="bank-connection-error">{errorMessage}</p> : null}
        {validationError ? <p className="bank-connection-error">{validationError}</p> : null}

        <form className="bank-connection-form" onSubmit={handleBankRelationshipSubmit}>
          <div className="bank-connection-grid">
            <div className="field-group">
              <label htmlFor="bank-owner-name">
                Account owner name <span className="required-marker">*</span>
              </label>
              <input
                id="bank-owner-name"
                type="text"
                value={bankRelationship.account_owner_name}
                onChange={(event) => updateBankRelationship("account_owner_name", event.target.value)}
                autoComplete="name"
                required
              />
            </div>

            <div className="field-group">
              <label htmlFor="bank-account-type">Bank account type</label>
              <select
                id="bank-account-type"
                value={bankRelationship.bank_account_type}
                onChange={(event) => updateBankRelationship("bank_account_type", event.target.value)}
              >
                {bankAccountTypeOptions.map((option) => (
                  <option key={option.label} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="field-group">
              <label htmlFor="bank-account-number">
                Bank account number <span className="required-marker">*</span>
              </label>
              <input
                id="bank-account-number"
                type="text"
                value={bankRelationship.bank_account_number}
                onChange={(event) => updateBankRelationship("bank_account_number", event.target.value)}
                inputMode="numeric"
                required
              />
            </div>

            <div className="field-group">
              <label htmlFor="bank-routing-number">
                Bank routing number <span className="required-marker">*</span>
              </label>
              <input
                id="bank-routing-number"
                type="text"
                value={bankRelationship.bank_routing_number}
                onChange={(event) => updateBankRelationship("bank_routing_number", event.target.value)}
                inputMode="numeric"
                required
              />
            </div>

            <div className="field-group field-span">
              <label htmlFor="bank-nickname">Nickname</label>
              <input
                id="bank-nickname"
                type="text"
                value={bankRelationship.nickname}
                onChange={(event) => updateBankRelationship("nickname", event.target.value)}
              />
            </div>
          </div>

          <div className="bank-connection-actions">
            <button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Connecting..." : "Connect Bank"}
            </button>
          </div>
        </form>

        {createdRelationship ? (
          <div className="bank-connection-result">
            <span>Relationship ID</span>
            <strong>{responseValue(createdRelationship, "id") || "-"}</strong>
          </div>
        ) : null}
      </div>

      <div className="bank-connection-panel">
        <header className="bank-connection-list-header">
          <h2>ACH Relationships</h2>
          <button type="button" className="secondary-button" onClick={fetchAchRelationships}>
            Refresh
          </button>
        </header>

        {isLoadingRelationships ? <p className="bank-connection-muted">Loading ACH relationships...</p> : null}
        {!isLoadingRelationships && achRelationships.length === 0 ? (
          <p className="bank-connection-muted">No ACH relationships connected.</p>
        ) : null}

        {achRelationships.length > 0 ? (
          <div className="bank-relationship-list">
            {achRelationships.map((relationship, index) => {
              const relationshipId = responseValue(relationship, "id") || `${index}`;
              const accountOwnerName = responseValue(relationship, "account_owner_name") || "-";
              const bankAccountType = responseValue(relationship, "bank_account_type") || "-";
              const nickname = responseValue(relationship, "nickname") || "Unnamed bank";
              const status = responseValue(relationship, "status") || "-";

              return (
                <article key={relationshipId} className="bank-relationship-item">
                  <div>
                    <h3>{nickname}</h3>
                    <p>{accountOwnerName}</p>
                  </div>
                  <div>
                    <span>Type</span>
                    <strong>{String(bankAccountType).split(".").pop()}</strong>
                  </div>
                  <div>
                    <span>Status</span>
                    <strong>{String(status).split(".").pop()}</strong>
                  </div>
                  <div>
                    <span>ID</span>
                    <strong>{relationshipId}</strong>
                  </div>
                </article>
              );
            })}
          </div>
        ) : null}
      </div>
    </section>
  );
}
