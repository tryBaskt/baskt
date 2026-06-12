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
          </div>
          {ach ? (
            <div className="details-list">
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
              <button className="primary-button" type="submit" disabled={isSubmitting}>Connect ACH</button>
            </div>
          )}
        </form>

        <form className="panel" onSubmit={submitBank}>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Bank</p>
              <h2>{bank ? "Connected bank" : "Connect bank"}</h2>
            </div>
          </div>
          {bank ? (
            <div className="details-list">
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
              <button className="primary-button" type="submit" disabled={isSubmitting}>Connect bank</button>
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
