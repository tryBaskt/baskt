import { useEffect, useState } from "react";
import { apiRequest } from "../lib/api";
import { ErrorBanner, LoadingState, SuccessBanner } from "../components/Status";
import { fundingSourceOptions } from "../data/options";

const sectionFields = {
  contact: [
    ["email_address", "Email address", "email"],
    ["phone_number", "Phone number", "tel"],
    ["street_address", "Street address", "text"],
    ["unit", "Unit", "text"],
    ["city", "City", "text"],
    ["state", "State", "text"],
    ["postal_code", "Postal code", "text"],
    ["country", "Country", "text"],
  ],
  identity: [
    ["given_name", "First name", "text"],
    ["middle_name", "Middle name", "text"],
    ["family_name", "Last name", "text"],
    ["date_of_birth", "Date of birth", "date"],
    ["tax_id_type", "Tax ID type", "text", true],
    ["country_of_citizenship", "Country of citizenship", "text"],
    ["country_of_birth", "Country of birth", "text"],
    ["country_of_tax_residence", "Country of tax residence", "text"],
    ["visa_type", "Visa type", "text"],
    ["visa_expiration_date", "Visa expiration date", "date"],
    ["date_of_departure_from_usa", "Departure date from USA", "date"],
    ["permanent_resident", "Permanent resident", "boolean"],
    ["funding_source", "Funding sources", "list"],
    ["annual_income_min", "Annual income minimum", "number"],
    ["annual_income_max", "Annual income maximum", "number"],
    ["liquid_net_worth_min", "Liquid net worth minimum", "number"],
    ["liquid_net_worth_max", "Liquid net worth maximum", "number"],
    ["total_net_worth_min", "Total net worth minimum", "number"],
    ["total_net_worth_max", "Total net worth maximum", "number"],
  ],
  disclosures: [
    ["immediate_family_exposed", "Immediate family politically exposed", "boolean", false, "Whether an immediate family member holds or has held a prominent public position."],
    ["is_control_person", "Control person", "boolean", false, "Whether you are a director, officer, or significant owner of a publicly traded company."],
    ["is_affiliated_exchange_or_finra", "Affiliated with an exchange or FINRA", "boolean", false, "Whether you or an immediate family member are employed by or associated with a securities exchange, FINRA, or a broker-dealer."],
    ["is_politically_exposed", "Politically exposed", "boolean", false, "Whether you hold or have held a prominent public position that may require additional financial review."],
    ["employment_status", "Employment status", "text"],
    ["employer_name", "Employer name", "text"],
    ["employer_address", "Employer address", "text"],
    ["employment_position", "Employment position", "text"],
  ],
};

const tradeAccountFields = [
  ["status", "Status", "text"],
  ["equity", "Equity", "currency"],
  ["cash_withdrawable", "Cash withdrawable", "currency"],
  ["cash_transferable", "Cash transferable", "currency"],
  ["previous_close", "Previous close", "datetime"],
  ["multiplier", "Multiplier", "text"],
  ["shorting_enabled", "Shorting enabled", "boolean"],
  ["trading_blocked", "Trading blocked", "boolean"],
  ["account_blocked", "Account blocked", "boolean"],
  ["last_cash", "Cash", "currency"],
  ["last_buying_power", "Buying power", "currency"],
  ["last_regt_buying_power", "Reg T buying power", "currency"],
  ["last_daytrading_buying_power", "Day trading buying power", "currency"],
  ["last_long_market_value", "Long market value", "currency"],
  ["last_short_market_value", "Short market value", "currency"],
  ["last_initial_margin", "Initial margin", "currency"],
  ["last_daytrade_count", "Day trade count", "number"],
  ["clearing_broker", "Clearing broker", "text"],
];
const TRADE_ACCOUNT_REQUEST_TIMEOUT_MS = 15000;

function FieldLabel({ label, description }) {
  if (!description) return label;
  const tooltipId = `tooltip-${label.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}`;
  return (
    <span className="field-label-with-help">
      <span>{label}</span>
      <button type="button" aria-label={`About ${label}`} aria-describedby={tooltipId}>?</button>
      <span className="field-tooltip" id={tooltipId} role="tooltip">{description}</span>
    </span>
  );
}

function humanizeText(value) {
  const text = String(value);
  if (!/^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+$/.test(text)) return text;
  return text.split("_").map((word) => (
    word === word.toUpperCase()
      ? word
      : `${word[0].toUpperCase()}${word.slice(1).toLowerCase()}`
  )).join(" ");
}

function displayValue(value) {
  if (Array.isArray(value)) return value.map(humanizeText).join(", ");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "—";
  return humanizeText(value);
}

function displayDate(value) {
  if (!value) return "—";
  const parsedDate = new Date(value);
  if (Number.isNaN(parsedDate.getTime())) return displayValue(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(parsedDate);
}

function displayDateTime(value) {
  if (!value) return "—";
  const parsedDate = new Date(value);
  if (Number.isNaN(parsedDate.getTime())) return displayValue(value);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(parsedDate);
}

function displayCurrency(value) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return displayValue(value);
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(numeric);
}

function displayTradeAccountValue(value, type) {
  if (type === "currency") return displayCurrency(value);
  if (type === "datetime") return displayDateTime(value);
  return displayValue(value);
}

function editableFields(section, data) {
  const isUsCitizen = String(data?.country_of_citizenship || "").toUpperCase() === "USA";
  return sectionFields[section].filter(([key, , , readOnly]) => (
    !readOnly && !(key === "permanent_resident" && isUsCitizen)
  ));
}

function initialForm(section, data) {
  return Object.fromEntries(
    editableFields(section, data).map(([key, , type]) => {
      const value = data?.[key];
      if (Array.isArray(value)) return [key, value];
      if (type === "list") return [key, value ? [value] : []];
      if (typeof value === "boolean") return [key, String(value)];
      return [key, value ?? ""];
    }),
  );
}

function updatePayload(section, form) {
  return Object.fromEntries(
    sectionFields[section].filter(([key]) => key in form).map(([key, , type]) => {
      const value = form[key];
      if (type === "boolean") {
        return [key, value === "" ? null : value === "true"];
      }
      if (type === "list") {
        return [key, Array.isArray(value) ? value : []];
      }
      if (section === "contact" && key === "street_address") {
        return [key, [String(value).trim()]];
      }
      return [key, value === "" ? null : value];
    }),
  );
}

function EditForm({ section, data, form, onChange, onCancel, onSave, isSaving }) {
  return (
    <form className="account-details-form" onSubmit={onSave}>
      {editableFields(section, data).map(([key, label, type, , description]) => (
        type === "list" ? (
          <div className="field funding-sources-field" key={key}>
            <span><FieldLabel label={label} description={description} /></span>
            <select
              value=""
              onChange={(event) => {
                const selectedValue = event.target.value;
                if (selectedValue && !form[key].includes(selectedValue)) {
                  onChange(key, [...form[key], selectedValue]);
                }
              }}
            >
              <option value="">Add a funding source</option>
              {fundingSourceOptions
                .filter((option) => !form[key].includes(option.value))
                .map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
            </select>
            <div className="funding-source-chips">
              {form[key].map((source) => {
                const option = fundingSourceOptions.find((item) => item.value === source);
                return (
                  <span key={source}>
                    {option?.label || source}
                    <button
                      type="button"
                      aria-label={`Remove ${option?.label || source}`}
                      onClick={() => onChange(key, form[key].filter((item) => item !== source))}
                    >
                      ×
                    </button>
                  </span>
                );
              })}
              {form[key].length === 0 && <small>No funding sources selected.</small>}
            </div>
          </div>
        ) : (
          <label key={key}>
            <span><FieldLabel label={label} description={description} /></span>
            {type === "boolean" ? (
            <select value={form[key]} onChange={(event) => onChange(key, event.target.value)}>
              <option value="">—</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
            ) : (
              <input
                type={type}
                value={form[key]}
                onChange={(event) => onChange(key, event.target.value)}
              />
            )}
          </label>
        )
      ))}
      <div className="settings-form-actions">
        <button className="settings-secondary-button" type="button" onClick={onCancel}>Cancel</button>
        <button className="settings-save-button" type="submit" disabled={isSaving}>
          {isSaving ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

function AccountSection({ title, section, data, editingSection, onEdit, form, setForm, onCancel, onSave, isSaving }) {
  const isEditing = editingSection === section;
  return (
    <section className="account-details-section">
      <div className="account-details-section-heading">
        <h2>{title}</h2>
        {!isEditing && (
          <button className="settings-edit-button" type="button" onClick={() => onEdit(section, data)}>
            Edit
          </button>
        )}
      </div>
      {isEditing ? (
        <EditForm
          section={section}
          data={data}
          form={form}
          onChange={(key, value) => setForm((current) => ({ ...current, [key]: value }))}
          onCancel={onCancel}
          onSave={onSave}
          isSaving={isSaving}
        />
      ) : (
        <dl className="account-details-list">
          {sectionFields[section].map(([key, label, , , description]) => (
            <div key={key}>
              <dt><FieldLabel label={label} description={description} /></dt>
              <dd>{displayValue(data?.[key])}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

function TradeAccountSection({ tradeAccount, status, onRetry }) {
  if (status === "loading") {
    return (
      <section className="account-details-section">
        <LoadingState title="Loading account details" message="Fetching your trading account data." />
      </section>
    );
  }

  if (status === "error") {
    return (
      <section className="account-details-section account-details-empty">
        <p>Account details could not be loaded.</p>
        <button className="settings-secondary-button" type="button" onClick={onRetry}>
          Retry
        </button>
      </section>
    );
  }

  return (
    <section className="account-details-section">
      <div className="account-details-section-heading">
        <h2>Trading Account</h2>
        <span>Read only</span>
      </div>
      <dl className="account-details-list">
        {tradeAccountFields.map(([key, label, type]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>{displayTradeAccountValue(tradeAccount?.[key], type)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default function SettingsPage() {
  const [account, setAccount] = useState(null);
  const [tradeAccount, setTradeAccount] = useState(null);
  const [settingsSection, setSettingsSection] = useState("profile");
  const [editingSection, setEditingSection] = useState(null);
  const [isEditingDisplayName, setIsEditingDisplayName] = useState(false);
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [form, setForm] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [tradeAccountStatus, setTradeAccountStatus] = useState("idle");
  const [tradeAccountReloadToken, setTradeAccountReloadToken] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let isActive = true;
    apiRequest("/accounts/account-details")
      .then((payload) => {
        if (isActive) setAccount(payload);
      })
      .catch((requestError) => {
        if (isActive) setError(requestError.message);
      })
      .finally(() => {
        if (isActive) setIsLoading(false);
      });
    return () => { isActive = false; };
  }, []);

  useEffect(() => {
    if (settingsSection !== "trade-account" || tradeAccount) {
      return undefined;
    }

    let isActive = true;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
    }, TRADE_ACCOUNT_REQUEST_TIMEOUT_MS);
    setTradeAccountStatus("loading");
    setError("");
    apiRequest("/accounts/trade-account", { signal: controller.signal })
      .then((payload) => {
        if (!isActive) return;
        setTradeAccount(payload);
        setTradeAccountStatus("loaded");
      })
      .catch((requestError) => {
        if (!isActive) return;
        setError(
          requestError.name === "AbortError"
            ? "Account details took too long to load. Please try again."
            : requestError.message
        );
        setTradeAccountStatus("error");
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
      });

    return () => {
      isActive = false;
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [settingsSection, tradeAccount, tradeAccountReloadToken]);

  function beginEditing(section, data) {
    setError("");
    setSuccess("");
    setEditingSection(section);
    setForm(initialForm(section, data));
  }

  async function saveSection(event) {
    event.preventDefault();
    if (
      editingSection === "identity"
      && Array.isArray(form.funding_source)
      && form.funding_source.length === 0
    ) {
      setError("Select at least one funding source.");
      return;
    }
    setIsSaving(true);
    setError("");
    setSuccess("");
    try {
      const updatedAccount = await apiRequest(`/accounts/account-details/${editingSection}`, {
        method: "PUT",
        body: JSON.stringify(updatePayload(editingSection, form)),
      });
      setAccount(updatedAccount);
      setSuccess(`${editingSection[0].toUpperCase()}${editingSection.slice(1)} updated.`);
      setEditingSection(null);
      setForm({});
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSaving(false);
    }
  }

  async function saveDisplayName(event) {
    event.preventDefault();
    const nextDisplayName = displayName.trim();
    if (!nextDisplayName) {
      setError("Display name is required.");
      return;
    }
    setIsSaving(true);
    setError("");
    setSuccess("");
    try {
      const updatedAccount = await apiRequest("/accounts/profile/display-name", {
        method: "PUT",
        body: JSON.stringify({ display_name: nextDisplayName }),
      });
      setAccount(updatedAccount);
      setDisplayName(updatedAccount.display_name);
      setIsEditingDisplayName(false);
      setSuccess("Display name updated.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSaving(false);
    }
  }

  async function saveDescription(event) {
    event.preventDefault();
    setIsSaving(true);
    setError("");
    setSuccess("");
    try {
      const updatedAccount = await apiRequest("/accounts/profile/description", {
        method: "PUT",
        body: JSON.stringify({ description: description.trim() }),
      });
      setAccount(updatedAccount);
      setDescription(updatedAccount.description || "");
      setIsEditingDescription(false);
      setSuccess("Description updated.");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setIsSaving(false);
    }
  }

  if (isLoading) {
    return <LoadingState title="Loading personal info" message="Fetching your account information." />;
  }

  return (
    <section className="settings-page" aria-labelledby="settings-heading">
      <header className="settings-heading">
        <h1 id="settings-heading">Settings</h1>
        <p>Review and manage your Baskt account.</p>
      </header>

      <div className="settings-layout">
        <aside className="settings-side-nav" aria-label="Settings navigation">
          <p>Account</p>
          <button
            className={settingsSection === "profile" ? "active" : ""}
            type="button"
            onClick={() => {
              setSettingsSection("profile");
              setEditingSection(null);
            }}
          >
            Profile
          </button>
          <button
            className={settingsSection === "account-details" ? "active" : ""}
            type="button"
            onClick={() => {
              setSettingsSection("account-details");
              setIsEditingDisplayName(false);
              setIsEditingDescription(false);
            }}
          >
            Personal Info
          </button>
          <button
            className={settingsSection === "trade-account" ? "active" : ""}
            type="button"
            onClick={() => {
              setSettingsSection("trade-account");
              setEditingSection(null);
              setIsEditingDisplayName(false);
              setIsEditingDescription(false);
            }}
          >
            Account Details
          </button>
        </aside>

        <div className="settings-content">
          <ErrorBanner message={error} />
          <SuccessBanner message={success} />
          {account && (
            settingsSection === "profile" ? (
              <>
                <div className="account-details-title">
                  <div><h2>Profile</h2></div>
                  <p>Manage how your name appears across Baskt.</p>
                </div>
                <section className="account-details-section profile-settings-section">
                  <div className="account-details-section-heading">
                    <h2>Display name</h2>
                    {!isEditingDisplayName && (
                      <button
                        className="settings-edit-button"
                        type="button"
                        onClick={() => {
                          setDisplayName(account.display_name);
                          setError("");
                          setSuccess("");
                          setIsEditingDisplayName(true);
                        }}
                      >
                        Edit
                      </button>
                    )}
                  </div>
                  {isEditingDisplayName ? (
                    <form className="profile-field-form" onSubmit={saveDisplayName}>
                      <label>
                        <span>Display name</span>
                        <input
                          value={displayName}
                          maxLength={50}
                          onChange={(event) => setDisplayName(event.target.value)}
                          required
                        />
                      </label>
                      <div className="settings-form-actions">
                        <button className="settings-secondary-button" type="button" onClick={() => setIsEditingDisplayName(false)}>Cancel</button>
                        <button className="settings-save-button" type="submit" disabled={isSaving}>{isSaving ? "Saving…" : "Save changes"}</button>
                      </div>
                    </form>
                  ) : (
                    <dl className="account-details-list"><div><dt>Display name</dt><dd>{account.display_name}</dd></div></dl>
                  )}
                </section>
                <section className="account-details-section profile-settings-section">
                  <div className="account-details-section-heading">
                    <h2>Description</h2>
                    {!isEditingDescription && (
                      <button
                        className="settings-edit-button"
                        type="button"
                        onClick={() => {
                          setDescription(account.description || "");
                          setError("");
                          setSuccess("");
                          setIsEditingDescription(true);
                        }}
                      >
                        Edit
                      </button>
                    )}
                  </div>
                  {isEditingDescription ? (
                    <form className="profile-field-form" onSubmit={saveDescription}>
                      <label>
                        <span>Description</span>
                        <textarea
                          value={description}
                          maxLength={500}
                          rows={4}
                          onChange={(event) => setDescription(event.target.value)}
                        />
                      </label>
                      <div className="settings-form-actions">
                        <button className="settings-secondary-button" type="button" onClick={() => setIsEditingDescription(false)}>Cancel</button>
                        <button className="settings-save-button" type="submit" disabled={isSaving}>{isSaving ? "Saving…" : "Save changes"}</button>
                      </div>
                    </form>
                  ) : (
                    <dl className="account-details-list"><div><dt>Description</dt><dd>{account.description}</dd></div></dl>
                  )}
                </section>
              </>
            ) : settingsSection === "account-details" ? (
            <>
              <div className="account-details-title">
                <div>
                  <h2>Personal Info</h2>
                </div>
                <p>Information used to maintain and service your account.</p>
              </div>

              <AccountSection title="Contact" section="contact" data={account.contact} editingSection={editingSection} onEdit={beginEditing} form={form} setForm={setForm} onCancel={() => setEditingSection(null)} onSave={saveSection} isSaving={isSaving} />
              <AccountSection title="Identity" section="identity" data={account.identity} editingSection={editingSection} onEdit={beginEditing} form={form} setForm={setForm} onCancel={() => setEditingSection(null)} onSave={saveSection} isSaving={isSaving} />
              <AccountSection title="Disclosures" section="disclosures" data={account.disclosures} editingSection={editingSection} onEdit={beginEditing} form={form} setForm={setForm} onCancel={() => setEditingSection(null)} onSave={saveSection} isSaving={isSaving} />

              <section className="account-details-section">
                <div className="account-details-section-heading"><h2>Agreements</h2><span>Read only</span></div>
                <div className="agreements-list">
                  {account.agreements.map((agreement, index) => (
                    <article key={`${agreement.agreement}-${agreement.signed_at}-${index}`}>
                      <strong>{displayValue(agreement.agreement)}</strong>
                      <span>Signed {displayDate(agreement.signed_at)}</span>
                      {agreement.revision && <span>Revision {agreement.revision}</span>}
                    </article>
                  ))}
                </div>
              </section>
            </>
            ) : (
              <>
                <div className="account-details-title">
                  <div>
                    <h2>Account Details</h2>
                  </div>
                  <p>Trading account balances and buying power from your brokerage account.</p>
                </div>

                <TradeAccountSection
                  tradeAccount={tradeAccount}
                  status={tradeAccountStatus}
                  onRetry={() => {
                    setTradeAccount(null);
                    setTradeAccountReloadToken((current) => current + 1);
                  }}
                />
              </>
            )
          )}
        </div>
      </div>
    </section>
  );
}
