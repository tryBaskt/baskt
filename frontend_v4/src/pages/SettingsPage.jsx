import { useEffect, useState } from "react";
import { apiRequest } from "../lib/api";
import { LoadingState } from "../components/Status";
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

export default function SettingsPage() {
  const [account, setAccount] = useState(null);
  const [settingsSection, setSettingsSection] = useState("profile");
  const [editingSection, setEditingSection] = useState(null);
  const [isEditingDisplayName, setIsEditingDisplayName] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [form, setForm] = useState({});
  const [isLoading, setIsLoading] = useState(true);
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

  if (isLoading) {
    return <LoadingState title="Loading account details" message="Fetching your account information." />;
  }

  return (
    <section className="settings-page" aria-labelledby="settings-heading">
      <header className="settings-heading">
        <p className="eyebrow">Account</p>
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
            }}
          >
            Account Details
          </button>
        </aside>

        <div className="settings-content">
          {error && <div className="alert alert-error">{error}</div>}
          {success && <div className="alert alert-success">{success}</div>}
          {account && (
            settingsSection === "profile" ? (
              <>
                <div className="account-details-title">
                  <div><p className="eyebrow">Account</p><h2>Profile</h2></div>
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
                    <form className="display-name-form" onSubmit={saveDisplayName}>
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
              </>
            ) : (
            <>
              <div className="account-details-title">
                <div>
                  <p className="eyebrow">Account</p>
                  <h2>Account Details</h2>
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
            )
          )}
        </div>
      </div>
    </section>
  );
}
