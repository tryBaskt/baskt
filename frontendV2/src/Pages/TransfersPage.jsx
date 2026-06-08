import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import "./TransfersPage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const TRANSFER_ROW_HEIGHT_PX = 76;
const TRANSFER_TABLE_HEADER_HEIGHT_PX = 28;
const TRANSFER_PAGINATION_HEIGHT_PX = 44;
const TRANSFER_PANEL_VERTICAL_PADDING_PX = 36;
const DEFAULT_TRANSFER_LIMIT = 3;

const EMPTY_ACH_FORM = {
  account_owner_name: "",
  bank_account_type: "CHECKING",
  bank_account_number: "",
  bank_routing_number: "",
  nickname: "",
};

const EMPTY_BANK_FORM = {
  name: "",
  bank_code_type: "ABA",
  bank_code: "",
  account_number: "",
  country: "",
  state_province: "",
  postal_code: "",
  city: "",
  street_address: "",
};

const EMPTY_TRANSFER_FORM = {
  amount: "",
  sourceKey: "",
};

function enumLabel(value) {
  if (!value) {
    return "None";
  }

  if (typeof value === "string") {
    return value;
  }

  return value.name || value.value || String(value);
}

function formatDate(value) {
  if (!value) {
    return "Not available";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") {
    return "Not available";
  }

  const amount = Number(value);
  if (Number.isNaN(amount)) {
    return String(value);
  }

  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
  }).format(amount);
}

function relationshipStatusClass(status) {
  const normalized = enumLabel(status).toLowerCase();

  if (normalized.includes("approved") || normalized.includes("complete")) {
    return "is-positive";
  }

  if (normalized.includes("reject") || normalized.includes("fail") || normalized.includes("cancel")) {
    return "is-negative";
  }

  return "";
}

function DetailRow({ label, value }) {
  return (
    <div className="transfer-detail-row">
      <span>{label}</span>
      <strong>{value || "Not available"}</strong>
    </div>
  );
}

function RelationshipBox({
  title,
  items,
  emptyActionLabel,
  isLoading,
  onAction,
  renderItem,
}) {
  const titleId = `${title.toLowerCase().replace(/\s+/g, "-")}-title`;

  return (
    <section className="transfer-side-box" aria-labelledby={titleId}>
      <div className="transfer-side-box-header">
        <h2 id={titleId}>{title}</h2>
        {items.length > 0 ? (
          <button type="button" className="transfer-change-button" onClick={onAction}>
            Change
          </button>
        ) : null}
      </div>

      {isLoading ? (
        <p className="transfers-muted">Loading...</p>
      ) : items.length > 0 ? (
        <div className="transfer-side-list">{items.map(renderItem)}</div>
      ) : (
        <button type="button" className="transfer-empty-action" onClick={onAction}>
          {emptyActionLabel}
        </button>
      )}
    </section>
  );
}

export default function TransfersPage() {
  const [transfers, setTransfers] = useState([]);
  const [achRelationships, setAchRelationships] = useState([]);
  const [banks, setBanks] = useState([]);
  const [tradeAccount, setTradeAccount] = useState(null);
  const [isTransfersLoading, setIsTransfersLoading] = useState(false);
  const [isAchLoading, setIsAchLoading] = useState(true);
  const [isBankLoading, setIsBankLoading] = useState(true);
  const [isTradeAccountLoading, setIsTradeAccountLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [modalType, setModalType] = useState(null);
  const [achForm, setAchForm] = useState(EMPTY_ACH_FORM);
  const [bankForm, setBankForm] = useState(EMPTY_BANK_FORM);
  const [transferModalType, setTransferModalType] = useState(null);
  const [transferForm, setTransferForm] = useState(EMPTY_TRANSFER_FORM);
  const [transferLimit, setTransferLimit] = useState(DEFAULT_TRANSFER_LIMIT);
  const [transferOffset, setTransferOffset] = useState(0);
  const [hasNextTransfersPage, setHasNextTransfersPage] = useState(false);
  const [hasPreviousTransfersPage, setHasPreviousTransfersPage] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [modalError, setModalError] = useState("");
  const transfersPanelRef = useRef(null);

  const token = useMemo(
    () => sessionStorage.getItem("idToken") || sessionStorage.getItem("accessToken") || "",
    []
  );

  const authHeaders = useMemo(
    () => ({
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }),
    [token]
  );

  useEffect(() => {
    if (!successMessage && !errorMessage) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setSuccessMessage("");
      setErrorMessage("");
    }, 2000);

    return () => window.clearTimeout(timeoutId);
  }, [successMessage, errorMessage]);

  useEffect(() => {
    if (!modalError) {
      return undefined;
    }

    const timeoutId = window.setTimeout(() => {
      setModalError("");
    }, 2000);

    return () => window.clearTimeout(timeoutId);
  }, [modalError]);

  useEffect(() => {
    if (!transfersPanelRef.current) {
      return undefined;
    }

    function updateTransferLimit() {
      const panel = transfersPanelRef.current;

      if (!panel) {
        return;
      }

      const headerHeight = panel.querySelector(".transfers-header")?.getBoundingClientRect().height || 0;
      const availableHeight = panel.getBoundingClientRect().height
        - headerHeight
        - TRANSFER_TABLE_HEADER_HEIGHT_PX
        - TRANSFER_PAGINATION_HEIGHT_PX
        - TRANSFER_PANEL_VERTICAL_PADDING_PX;
      const nextLimit = Math.max(1, Math.floor(availableHeight / TRANSFER_ROW_HEIGHT_PX));

      setTransferLimit((currentLimit) => (currentLimit === nextLimit ? currentLimit : nextLimit));
      setTransferOffset((currentOffset) => {
        const alignedOffset = Math.floor(currentOffset / nextLimit) * nextLimit;
        return currentOffset === alignedOffset ? currentOffset : alignedOffset;
      });
    }

    updateTransferLimit();

    const observer = new ResizeObserver(updateTransferLimit);
    observer.observe(transfersPanelRef.current);

    return () => observer.disconnect();
  }, []);

  const fetchAchRelationships = useCallback(async ({ signal, showLoading = true } = {}) => {
    if (showLoading) {
      setIsAchLoading(true);
    }

    try {
      const response = await fetch(`${API_BASE_URL}/accounts/ach-relationships`, {
        headers: authHeaders,
        signal,
      });
      const payload = await response.json().catch(() => []);

      if (!response.ok) {
        throw new Error(payload?.detail || `Failed to load ACH relationships (${response.status}).`);
      }

      if (!signal?.aborted) {
        setAchRelationships(Array.isArray(payload) ? payload : []);
      }
    } finally {
      if (!signal?.aborted) {
        setIsAchLoading(false);
      }
    }
  }, [authHeaders]);

  const fetchBanks = useCallback(async ({ signal, showLoading = true } = {}) => {
    if (showLoading) {
      setIsBankLoading(true);
    }

    try {
      const response = await fetch(`${API_BASE_URL}/accounts/banks`, {
        headers: authHeaders,
        signal,
      });
      const payload = await response.json().catch(() => []);

      if (!response.ok) {
        throw new Error(payload?.detail || `Failed to load banks (${response.status}).`);
      }

      if (!signal?.aborted) {
        setBanks(Array.isArray(payload) ? payload : []);
      }
    } finally {
      if (!signal?.aborted) {
        setIsBankLoading(false);
      }
    }
  }, [authHeaders]);

  const fetchTransfers = useCallback(async ({ signal, limit = transferLimit, offset = transferOffset } = {}) => {
    setIsTransfersLoading(true);

    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });

    try {
      const response = await fetch(`${API_BASE_URL}/accounts/transfers?${params.toString()}`, {
        headers: authHeaders,
        signal,
      });
      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(payload?.detail || `Failed to load transfers (${response.status}).`);
      }

      const transferItems = Array.isArray(payload) ? payload : payload.items;

      if (!signal?.aborted) {
        setTransfers(Array.isArray(transferItems) ? transferItems : []);
        setHasNextTransfersPage(Boolean(payload?.has_next));
        setHasPreviousTransfersPage(Boolean(payload?.has_previous));
      }
    } finally {
      if (!signal?.aborted) {
        setIsTransfersLoading(false);
      }
    }
  }, [authHeaders, transferLimit, transferOffset]);

  const fetchTradeAccount = useCallback(async ({ signal, showLoading = true } = {}) => {
    if (showLoading) {
      setIsTradeAccountLoading(true);
    }

    try {
      const response = await fetch(`${API_BASE_URL}/accounts/trade-account`, {
        headers: authHeaders,
        signal,
      });
      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(payload?.detail || `Failed to load trade account (${response.status}).`);
      }

      if (!signal?.aborted) {
        setTradeAccount(payload && typeof payload === "object" ? payload : null);
      }
    } finally {
      if (!signal?.aborted) {
        setIsTradeAccountLoading(false);
      }
    }
  }, [authHeaders]);

  useEffect(() => {
    const controller = new AbortController();

    setErrorMessage("");
    setIsAchLoading(true);
    setIsBankLoading(true);

    fetchAchRelationships({ signal: controller.signal, showLoading: false }).catch((error) => {
      if (!controller.signal.aborted) {
        setErrorMessage(error?.message || "Unable to load ACH relationships.");
        setAchRelationships([]);
      }
    });

    fetchBanks({ signal: controller.signal, showLoading: false }).catch((error) => {
      if (!controller.signal.aborted) {
        setErrorMessage(error?.message || "Unable to load banks.");
        setBanks([]);
      }
    });

    fetchTradeAccount({ signal: controller.signal, showLoading: false }).catch((error) => {
      if (!controller.signal.aborted) {
        setErrorMessage(error?.message || "Unable to load trade account.");
        setTradeAccount(null);
      }
    });

    return () => controller.abort();
  }, [fetchAchRelationships, fetchBanks, fetchTradeAccount]);

  useEffect(() => {
    const controller = new AbortController();

    fetchTransfers({
      signal: controller.signal,
      limit: transferLimit,
      offset: transferOffset,
    }).catch((error) => {
      if (!controller.signal.aborted) {
        setErrorMessage(error?.message || "Unable to load transfers.");
        setTransfers([]);
        setHasNextTransfersPage(false);
        setHasPreviousTransfersPage(transferOffset > 0);
      }
    });

    return () => controller.abort();
  }, [fetchTransfers, transferLimit, transferOffset]);

  const sortedTransfers = useMemo(() => {
    return [...transfers].sort((first, second) => {
      const firstDate = new Date(first.updated_at || first.created_at || 0).getTime();
      const secondDate = new Date(second.updated_at || second.created_at || 0).getTime();
      return secondDate - firstDate;
    });
  }, [transfers]);

  const connectedFundingSources = useMemo(() => {
    const achOptions = achRelationships.map((relationship) => ({
      key: `ACH:${relationship.id}`,
      type: "ACH",
      id: relationship.id,
      label: `ACH - ${relationship.account_owner_name || relationship.nickname || relationship.id}`,
    }));

    const bankOptions = banks.map((bank) => ({
      key: `BANK:${bank.id}`,
      type: "BANK",
      id: bank.id,
      label: `Bank - ${bank.name || bank.id}`,
    }));

    return [...achOptions, ...bankOptions].filter((option) => option.id);
  }, [achRelationships, banks]);

  const cashWithdrawable = useMemo(() => {
    const rawValue = tradeAccount?.cash_withdrawable;
    const parsedValue = Number(rawValue);

    return Number.isFinite(parsedValue) ? parsedValue : 0;
  }, [tradeAccount]);

  function goToPreviousTransfersPage() {
    setTransferOffset((currentOffset) => Math.max(0, currentOffset - transferLimit));
  }

  function goToNextTransfersPage() {
    setTransferOffset((currentOffset) => currentOffset + transferLimit);
  }

  function openRelationshipModal(type) {
    setModalType(type);
    setModalError("");
    setSuccessMessage("");

    if (type === "ach") {
      const existing = achRelationships[0];
      setAchForm({
        account_owner_name: existing?.account_owner_name || "",
        bank_account_type: enumLabel(existing?.bank_account_type) === "None" ? "CHECKING" : enumLabel(existing?.bank_account_type),
        bank_account_number: existing?.bank_account_number || "",
        bank_routing_number: existing?.bank_routing_number || "",
        nickname: existing?.nickname || "",
      });
      return;
    }

    const existing = banks[0];
    setBankForm({
      name: existing?.name || "",
      bank_code_type: enumLabel(existing?.bank_code_type) === "None" ? "ABA" : enumLabel(existing?.bank_code_type),
      bank_code: existing?.bank_code || "",
      account_number: existing?.account_number || "",
      country: existing?.country || "",
      state_province: existing?.state_province || "",
      postal_code: existing?.postal_code || "",
      city: existing?.city || "",
      street_address: existing?.street_address || "",
    });
  }

  function closeRelationshipModal() {
    if (!isSubmitting) {
      setModalType(null);
      setModalError("");
    }
  }

  function openTransferModal(type) {
    setTransferModalType(type);
    setModalError("");
    setSuccessMessage("");
    setTransferForm({
      ...EMPTY_TRANSFER_FORM,
      sourceKey: connectedFundingSources[0]?.key || "",
    });
  }

  function closeTransferModal() {
    if (!isSubmitting) {
      setTransferModalType(null);
      setModalError("");
    }
  }

  function updateAchForm(event) {
    const { name, value } = event.target;
    setAchForm((current) => ({ ...current, [name]: value }));
  }

  function updateBankForm(event) {
    const { name, value } = event.target;
    setBankForm((current) => ({ ...current, [name]: value }));
  }

  function updateTransferForm(event) {
    const { name, value } = event.target;
    setTransferForm((current) => ({ ...current, [name]: value }));
  }

  async function submitRelationshipForm(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setModalError("");

    const isAch = modalType === "ach";
    const endpoint = isAch ? "/accounts/ach-relationship" : "/accounts/bank";
    const hasExistingConnection = isAch ? achRelationships.length > 0 : banks.length > 0;
    const rawPayload = isAch ? achForm : bankForm;
    const payload = Object.fromEntries(
      Object.entries(rawPayload).filter(([, value]) => value !== "")
    );

    try {
      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: hasExistingConnection ? "PUT" : "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify(payload),
      });
      const responsePayload = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(responsePayload?.detail || `Failed to connect ${isAch ? "ACH" : "bank"} (${response.status}).`);
      }

      setSuccessMessage(isAch ? "ACH relationship submitted." : "Bank relationship submitted.");
      setModalType(null);

      if (isAch) {
        await fetchAchRelationships();
      } else {
        await fetchBanks();
      }
    } catch (error) {
      setModalError(error?.message || "Unable to submit connection.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitTransferForm(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setModalError("");

    const selectedSource = connectedFundingSources.find((source) => source.key === transferForm.sourceKey);
    if (!selectedSource) {
      setModalError("Connect an ACH relationship or bank before creating a transfer.");
      setIsSubmitting(false);
      return;
    }

    const transferAmount = Number(transferForm.amount);
    if (!Number.isFinite(transferAmount) || transferAmount <= 0) {
      setModalError("Enter a valid transfer amount.");
      setIsSubmitting(false);
      return;
    }

    if (transferModalType === "withdraw" && transferAmount > cashWithdrawable) {
      setModalError(`Withdrawal amount cannot exceed ${formatMoney(cashWithdrawable)}.`);
      setIsSubmitting(false);
      return;
    }

    const payload = {
      amount: transferForm.amount,
      direction: transferModalType === "deposit" ? "INCOMING" : "OUTGOING",
      funding_source_type: selectedSource.type,
      timing: "IMMEDIATE",
      fee_payment_method: "USER",
      ...(selectedSource.type === "ACH" ? { relationship_id: selectedSource.id } : { bank_id: selectedSource.id }),
    };

    try {
      const response = await fetch(`${API_BASE_URL}/accounts/transfer`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeaders,
        },
        body: JSON.stringify(payload),
      });
      const responsePayload = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(responsePayload?.detail || `Failed to create transfer (${response.status}).`);
      }

      setSuccessMessage(transferModalType === "deposit" ? "Deposit submitted." : "Withdrawal submitted.");
      setTransferModalType(null);
      setTransferOffset(0);
      await Promise.all([
        fetchTransfers({ limit: transferLimit, offset: 0 }),
        fetchTradeAccount(),
      ]);
    } catch (error) {
      setModalError(error?.message || "Unable to submit transfer.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="transfers-page" aria-labelledby="transfers-title">
      <div className="transfers-layout">
        <section className="transfers-panel transfers-main-panel" aria-labelledby="transfers-title" ref={transfersPanelRef}>
          <div className="transfers-header">
            <div>
              <h1 id="transfers-title">Transfers</h1>
              <p>
                {isTransfersLoading
                  ? "Loading account transfer activity"
                  : sortedTransfers.length > 0
                    ? `${transferOffset + 1}-${transferOffset + sortedTransfers.length} transfer records`
                    : "0 transfer records"}
              </p>
            </div>
          </div>

          {isTransfersLoading ? (
            <p className="transfers-muted">Loading transfers...</p>
          ) : sortedTransfers.length > 0 ? (
            <div className="transfers-table" role="table" aria-label="Account transfers">
              <div className="transfers-table-head" role="row">
                <span>Type</span>
                <span>Amount</span>
                <span>Direction</span>
                <span>Status</span>
                <span>Updated</span>
              </div>
              <div className="transfers-table-body">
                {sortedTransfers.map((transfer) => {
                  const status = enumLabel(transfer.status);

                  return (
                    <article className="transfer-row" key={transfer.id || `${transfer.created_at}-${transfer.amount}`}>
                      <div>
                        <span className="transfer-mobile-label">Type</span>
                        <strong>{enumLabel(transfer.type || transfer.transfer_type)}</strong>
                        <small>{transfer.id || "No transfer id"}</small>
                      </div>
                      <div>
                        <span className="transfer-mobile-label">Amount</span>
                        <strong>{formatMoney(transfer.amount)}</strong>
                      </div>
                      <div>
                        <span className="transfer-mobile-label">Direction</span>
                        <strong>{enumLabel(transfer.direction)}</strong>
                      </div>
                      <div>
                        <span className="transfer-mobile-label">Status</span>
                        <strong className={`transfer-status ${relationshipStatusClass(status)}`}>{status}</strong>
                      </div>
                      <div>
                        <span className="transfer-mobile-label">Updated</span>
                        <strong>{formatDate(transfer.updated_at || transfer.created_at)}</strong>
                      </div>
                    </article>
                  );
                })}
              </div>
              <div className="transfers-pagination">
                <button
                  type="button"
                  onClick={goToPreviousTransfersPage}
                  disabled={!hasPreviousTransfersPage || isTransfersLoading}
                >
                  Previous
                </button>
                <span>Page {Math.floor(transferOffset / transferLimit) + 1}</span>
                <button
                  type="button"
                  onClick={goToNextTransfersPage}
                  disabled={!hasNextTransfersPage || isTransfersLoading}
                >
                  Next
                </button>
              </div>
            </div>
          ) : (
            <p className="transfers-empty">No transfers found for this account.</p>
          )}
        </section>

        <aside className="transfers-side-panel" aria-label="Funding relationships">
          <RelationshipBox
            title="ACH"
            items={achRelationships}
            emptyActionLabel="Connect via ACH"
            isLoading={isAchLoading}
            onAction={() => openRelationshipModal("ach")}
            renderItem={(relationship) => (
              <article className="transfer-relationship-card" key={relationship.id || relationship.account_owner_name}>
                <div className="transfer-relationship-title">
                  <strong>{relationship.account_owner_name || "ACH relationship"}</strong>
                  <span className={`transfer-status ${relationshipStatusClass(relationship.status)}`}>
                    {enumLabel(relationship.status)}
                  </span>
                </div>
                <DetailRow label="Account type" value={enumLabel(relationship.bank_account_type)} />
                <DetailRow label="Routing" value={relationship.bank_routing_number} />
                <DetailRow label="Account" value={relationship.bank_account_number} />
              </article>
            )}
          />

          <RelationshipBox
            title="Bank"
            items={banks}
            emptyActionLabel="Connect to your Bank"
            isLoading={isBankLoading}
            onAction={() => openRelationshipModal("bank")}
            renderItem={(bank) => (
              <article className="transfer-relationship-card" key={bank.id || bank.name}>
                <div className="transfer-relationship-title">
                  <strong>{bank.name || "Bank relationship"}</strong>
                  <span className={`transfer-status ${relationshipStatusClass(bank.status)}`}>{enumLabel(bank.status)}</span>
                </div>
                <DetailRow label="Code type" value={enumLabel(bank.bank_code_type)} />
                <DetailRow label="Bank code" value={bank.bank_code} />
                <DetailRow label="Account" value={bank.account_number} />
              </article>
            )}
          />

          <div className="transfer-money-actions">
            <button type="button" className="transfer-money-button" onClick={() => openTransferModal("deposit")}>
              Deposit
            </button>
            <button type="button" className="transfer-money-button is-secondary" onClick={() => openTransferModal("withdraw")}>
              Withdraw
            </button>
          </div>
        </aside>
      </div>

      {modalType ? (
        <div className="transfer-modal-backdrop" role="presentation" onMouseDown={closeRelationshipModal}>
          <section
            className="transfer-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="transfer-modal-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="transfer-modal-header">
              <h2 id="transfer-modal-title">
                {modalType === "ach" ? "ACH information" : "Bank information"}
              </h2>
              <button type="button" className="transfer-modal-close" onClick={closeRelationshipModal}>
                Close
              </button>
            </div>

            {modalError ? <p className="transfers-error">{modalError}</p> : null}

            <form className="transfer-modal-form" onSubmit={submitRelationshipForm}>
              {modalType === "ach" ? (
                <>
                  <label>
                    <span>Account owner name</span>
                    <input name="account_owner_name" value={achForm.account_owner_name} onChange={updateAchForm} required />
                  </label>
                  <label>
                    <span>Account type</span>
                    <select name="bank_account_type" value={achForm.bank_account_type} onChange={updateAchForm} required>
                      <option value="CHECKING">Checking</option>
                      <option value="SAVINGS">Savings</option>
                    </select>
                  </label>
                  <label>
                    <span>Account number</span>
                    <input name="bank_account_number" value={achForm.bank_account_number} onChange={updateAchForm} required />
                  </label>
                  <label>
                    <span>Routing number</span>
                    <input name="bank_routing_number" value={achForm.bank_routing_number} onChange={updateAchForm} required />
                  </label>
                  <label className="transfer-modal-field-wide">
                    <span>Nickname</span>
                    <input name="nickname" value={achForm.nickname} onChange={updateAchForm} />
                  </label>
                </>
              ) : (
                <>
                  <label>
                    <span>Bank name</span>
                    <input name="name" value={bankForm.name} onChange={updateBankForm} required />
                  </label>
                  <label>
                    <span>Bank code type</span>
                    <select name="bank_code_type" value={bankForm.bank_code_type} onChange={updateBankForm} required>
                      <option value="ABA">ABA</option>
                      <option value="BIC">BIC</option>
                    </select>
                  </label>
                  <label>
                    <span>Bank code</span>
                    <input name="bank_code" value={bankForm.bank_code} onChange={updateBankForm} required />
                  </label>
                  <label>
                    <span>Account number</span>
                    <input name="account_number" value={bankForm.account_number} onChange={updateBankForm} required />
                  </label>
                  <label>
                    <span>Country</span>
                    <input name="country" value={bankForm.country} onChange={updateBankForm} />
                  </label>
                  <label>
                    <span>State / province</span>
                    <input name="state_province" value={bankForm.state_province} onChange={updateBankForm} />
                  </label>
                  <label>
                    <span>Postal code</span>
                    <input name="postal_code" value={bankForm.postal_code} onChange={updateBankForm} />
                  </label>
                  <label>
                    <span>City</span>
                    <input name="city" value={bankForm.city} onChange={updateBankForm} />
                  </label>
                  <label className="transfer-modal-field-wide">
                    <span>Street address</span>
                    <input name="street_address" value={bankForm.street_address} onChange={updateBankForm} />
                  </label>
                </>
              )}

              <div className="transfer-modal-actions">
                <button type="button" className="transfer-secondary-button" onClick={closeRelationshipModal}>
                  Cancel
                </button>
                <button type="submit" className="transfer-primary-button" disabled={isSubmitting}>
                  {isSubmitting ? "Submitting..." : "Submit"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}

      {transferModalType ? (
        <div className="transfer-modal-backdrop" role="presentation" onMouseDown={closeTransferModal}>
          <section
            className="transfer-modal transfer-money-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="transfer-money-modal-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="transfer-modal-header">
              <h2 id="transfer-money-modal-title">
                {transferModalType === "deposit" ? "Deposit funds" : "Withdraw funds"}
              </h2>
              <button type="button" className="transfer-modal-close" onClick={closeTransferModal}>
                Close
              </button>
            </div>

            {modalError ? <p className="transfers-error">{modalError}</p> : null}

            <form className="transfer-modal-form transfer-money-form" onSubmit={submitTransferForm}>
              <label>
                <span>Amount</span>
                <input
                  name="amount"
                  type="number"
                  min="0.01"
                  max={transferModalType === "withdraw" ? cashWithdrawable : undefined}
                  step="0.01"
                  value={transferForm.amount}
                  onChange={updateTransferForm}
                  required
                />
              </label>
              {transferModalType === "withdraw" ? (
                <p className="transfer-available-cash">
                  Available to withdraw:{" "}
                  <strong>
                    {isTradeAccountLoading ? "Loading..." : formatMoney(cashWithdrawable)}
                  </strong>
                </p>
              ) : null}
              <label>
                <span>Funding source</span>
                <select
                  name="sourceKey"
                  value={transferForm.sourceKey}
                  onChange={updateTransferForm}
                  required
                  disabled={connectedFundingSources.length === 0}
                >
                  {connectedFundingSources.length > 0 ? (
                    connectedFundingSources.map((source) => (
                      <option key={source.key} value={source.key}>
                        {source.label}
                      </option>
                    ))
                  ) : (
                    <option value="">No connected ACH or bank</option>
                  )}
                </select>
              </label>

              <div className="transfer-modal-actions">
                <button type="button" className="transfer-secondary-button" onClick={closeTransferModal}>
                  Cancel
                </button>
                <button
                  type="submit"
                  className="transfer-primary-button"
                  disabled={
                    isSubmitting
                    || connectedFundingSources.length === 0
                    || (transferModalType === "withdraw" && (isTradeAccountLoading || cashWithdrawable <= 0))
                  }
                >
                  {isSubmitting ? "Submitting..." : "Submit"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </section>
  );
}
