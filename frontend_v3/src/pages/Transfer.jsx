import { useEffect, useState } from "react";
import { ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { apiRequest, toQuery } from "../lib/api";
import { currency, formatDateTime } from "../lib/format";

const initialAch = {
  account_owner_name: "",
  bank_account_type: "CHECKING",
  bank_account_number: "",
  bank_routing_number: "",
  nickname: "",
};

const initialBank = {
  name: "",
  bank_code_type: "ABA",
  bank_code: "",
  account_number: "",
  country: "USA",
  state_province: "",
  postal_code: "",
  city: "",
  street_address: "",
};

function achToForm(ach) {
  return {
    account_owner_name: ach?.account_owner_name || "",
    bank_account_type: ach?.bank_account_type || "CHECKING",
    bank_account_number: ach?.bank_account_number || "",
    bank_routing_number: ach?.bank_routing_number || "",
    nickname: ach?.nickname || "",
  };
}

function bankToForm(bank) {
  return {
    name: bank?.name || "",
    bank_code_type: bank?.bank_code_type || "ABA",
    bank_code: bank?.bank_code || "",
    account_number: bank?.alpaca_account_number || bank?.account_number || "",
    country: bank?.country || "USA",
    state_province: bank?.state_province || "",
    postal_code: bank?.postal_code || "",
    city: bank?.city || "",
    street_address: bank?.street_address || "",
  };
}

function statusClassName(status) {
  const normalizedStatus = String(status || "").toLowerCase();
  if (["approved", "active", "verified"].includes(normalizedStatus)) {
    return "status-pill success";
  }

  if (["pending", "submitted", "queued"].includes(normalizedStatus)) {
    return "status-pill pending";
  }

  if (["rejected", "failed", "cancelled", "canceled", "inactive"].includes(normalizedStatus)) {
    return "status-pill danger";
  }

  return "status-pill";
}

function StatusPill({ status }) {
  return (
    <span className={statusClassName(status)}>
      <span aria-hidden="true" />
      {status || "Unknown"}
    </span>
  );
}

export default function Transfer() {
  const [achRelationships, setAchRelationships] = useState([]);
  const [banks, setBanks] = useState([]);
  const [transfers, setTransfers] = useState([]);
  const [achForm, setAchForm] = useState(initialAch);
  const [bankForm, setBankForm] = useState(initialBank);
  const [transferForm, setTransferForm] = useState({
    amount: "",
    direction: "INCOMING",
    funding_source_type: "ACH",
    timing: "IMMEDIATE",
  });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isEditingAch, setIsEditingAch] = useState(false);
  const [isEditingBank, setIsEditingBank] = useState(false);

  async function loadFunding() {
    const [achPayload, bankPayload, transferPayload] = await Promise.all([
      apiRequest("/accounts/ach-relationships"),
      apiRequest("/accounts/banks"),
      apiRequest(`/accounts/transfers${toQuery({ limit: 20, offset: 0 })}`),
    ]);
    setAchRelationships(achPayload?.list_ach_relationship || []);
    setBanks(bankPayload?.list_banks || []);
    setTransfers(transferPayload?.items || []);
  }

  useEffect(() => {
    let ignore = false;
    async function run() {
      try {
        setIsLoading(true);
        await loadFunding();
      } catch (fundingError) {
        if (!ignore) {
          setError(fundingError?.message || "Could not load transfer data.");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }
    run();
    return () => {
      ignore = true;
    };
  }, []);

  async function submitAch(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    try {
      setIsSubmitting(true);
      await apiRequest("/accounts/ach-relationship", {
        method: achRelationships.length ? "PUT" : "POST",
        body: JSON.stringify(achForm),
      });
      setSuccess("ACH relationship saved.");
      await loadFunding();
      setIsEditingAch(false);
    } catch (achError) {
      setError(achError?.message || "Could not save ACH relationship.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitBank(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    try {
      setIsSubmitting(true);
      await apiRequest("/accounts/bank", {
        method: banks.length ? "PUT" : "POST",
        body: JSON.stringify(bankForm),
      });
      setSuccess("Bank saved.");
      await loadFunding();
      setIsEditingBank(false);
    } catch (bankError) {
      setError(bankError?.message || "Could not save bank.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitTransfer(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    const selectedAch = achRelationships[0];
    const selectedBank = banks[0];
    const payload = {
      ...transferForm,
      amount: String(transferForm.amount),
      relationship_id: transferForm.funding_source_type === "ACH" ? selectedAch?.relationship_id : undefined,
      bank_id: transferForm.funding_source_type === "BANK" ? selectedBank?.bank_id : undefined,
    };

    try {
      setIsSubmitting(true);
      await apiRequest("/accounts/transfer", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setSuccess("Transfer submitted.");
      setTransferForm((current) => ({ ...current, amount: "" }));
      await loadFunding();
    } catch (transferError) {
      setError(transferError?.message || "Could not create transfer.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading) {
    return <LoadingState title="Loading transfers" message="Checking linked funding sources." />;
  }

  const ach = achRelationships[0];
  const bank = banks[0];
  const shouldShowAchForm = !ach || isEditingAch;
  const shouldShowBankForm = !bank || isEditingBank;

  return (
    <div className="page-stack">
      <ErrorBanner message={error} />
      <SuccessBanner message={success} />

      <section className="split-grid">
        <form className="panel" onSubmit={submitAch}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">ACH relationship</p>
              <h2>{ach ? "Connected ACH" : "Connect ACH"}</h2>
            </div>
            {ach && !isEditingAch ? (
              <button
                className="ghost-button"
                type="button"
                onClick={() => {
                  setAchForm(achToForm(ach));
                  setIsEditingAch(true);
                }}
              >
                Change
              </button>
            ) : null}
          </div>
          {!shouldShowAchForm ? (
            <div className="details-list">
              <div className="funding-status-row">
                <span>Status</span>
                <StatusPill status={ach.status} />
              </div>
              <span>Owner <strong>{ach.account_owner_name}</strong></span>
              <span>Nickname <strong>{ach.nickname || "None"}</strong></span>
              <span>Routing <strong>{ach.bank_routing_number}</strong></span>
              <span>Account <strong>{ach.bank_account_number}</strong></span>
            </div>
          ) : (
            <div className="form-grid one">
              <input placeholder="Account owner" value={achForm.account_owner_name} onChange={(e) => setAchForm((c) => ({ ...c, account_owner_name: e.target.value }))} required />
              <select value={achForm.bank_account_type} onChange={(e) => setAchForm((c) => ({ ...c, bank_account_type: e.target.value }))}>
                <option value="CHECKING">Checking</option>
                <option value="SAVINGS">Savings</option>
              </select>
              <input placeholder="Account number" value={achForm.bank_account_number} onChange={(e) => setAchForm((c) => ({ ...c, bank_account_number: e.target.value }))} required />
              <input placeholder="Routing number" value={achForm.bank_routing_number} onChange={(e) => setAchForm((c) => ({ ...c, bank_routing_number: e.target.value }))} required />
              <input placeholder="Nickname" value={achForm.nickname} onChange={(e) => setAchForm((c) => ({ ...c, nickname: e.target.value }))} />
              <div className="button-row">
                {ach ? (
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={isSubmitting}
                    onClick={() => {
                      setAchForm(initialAch);
                      setIsEditingAch(false);
                    }}
                  >
                    Cancel
                  </button>
                ) : null}
                <button className="primary-button" type="submit" disabled={isSubmitting}>
                  {ach ? "Save ACH changes" : "Connect ACH"}
                </button>
              </div>
            </div>
          )}
        </form>

        <form className="panel" onSubmit={submitBank}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Bank</p>
              <h2>{bank ? "Connected bank" : "Connect bank"}</h2>
            </div>
            {bank && !isEditingBank ? (
              <button
                className="ghost-button"
                type="button"
                onClick={() => {
                  setBankForm(bankToForm(bank));
                  setIsEditingBank(true);
                }}
              >
                Change
              </button>
            ) : null}
          </div>
          {!shouldShowBankForm ? (
            <div className="details-list">
              <div className="funding-status-row">
                <span>Status</span>
                <StatusPill status={bank.status} />
              </div>
              <span>Name <strong>{bank.name}</strong></span>
              <span>Bank code <strong>{bank.bank_code}</strong></span>
              <span>Account <strong>{bank.alpaca_account_number}</strong></span>
            </div>
          ) : (
            <div className="form-grid one">
              <input placeholder="Bank name" value={bankForm.name} onChange={(e) => setBankForm((c) => ({ ...c, name: e.target.value }))} required />
              <input placeholder="Bank code" value={bankForm.bank_code} onChange={(e) => setBankForm((c) => ({ ...c, bank_code: e.target.value }))} required />
              <input placeholder="Account number" value={bankForm.account_number} onChange={(e) => setBankForm((c) => ({ ...c, account_number: e.target.value }))} required />
              <input placeholder="City" value={bankForm.city} onChange={(e) => setBankForm((c) => ({ ...c, city: e.target.value }))} />
              <div className="button-row">
                {bank ? (
                  <button
                    className="ghost-button"
                    type="button"
                    disabled={isSubmitting}
                    onClick={() => {
                      setBankForm(initialBank);
                      setIsEditingBank(false);
                    }}
                  >
                    Cancel
                  </button>
                ) : null}
                <button className="primary-button" type="submit" disabled={isSubmitting}>
                  {bank ? "Save bank changes" : "Connect bank"}
                </button>
              </div>
            </div>
          )}
        </form>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Move money</p>
            <h2>Deposit or withdraw funds</h2>
          </div>
        </div>
        <form className="transfer-form" onSubmit={submitTransfer}>
          <input type="number" min="0" step="0.01" placeholder="Amount" value={transferForm.amount} onChange={(e) => setTransferForm((c) => ({ ...c, amount: e.target.value }))} required />
          <select value={transferForm.direction} onChange={(e) => setTransferForm((c) => ({ ...c, direction: e.target.value }))}>
            <option value="INCOMING">Deposit</option>
            <option value="OUTGOING">Withdraw</option>
          </select>
          <select value={transferForm.funding_source_type} onChange={(e) => setTransferForm((c) => ({ ...c, funding_source_type: e.target.value }))}>
            <option value="ACH" disabled={!ach}>ACH</option>
            <option value="BANK" disabled={!bank}>Bank</option>
          </select>
          <button className="primary-button" type="submit" disabled={isSubmitting || (!ach && !bank)}>Submit transfer</button>
        </form>
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">History</p>
            <h2>Past transfers</h2>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Direction</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Source</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {transfers.map((transfer, index) => (
                <tr key={`${transfer.created_at}-${index}`}>
                  <td>{transfer.direction}</td>
                  <td>{currency(transfer.amount)}</td>
                  <td><span className="pill">{transfer.status}</span></td>
                  <td>{transfer.relationship_id ? "ACH" : "Bank"}</td>
                  <td>{formatDateTime(transfer.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!transfers.length ? <p className="muted">No transfers yet.</p> : null}
        </div>
      </section>
    </div>
  );
}
