import { useMemo, useState } from "react";
import { apiRequest } from "../lib/api";
import {
  countryOptions,
  employmentStatusOptions,
  fundingSourceOptions,
  taxIdTypeOptions,
  usStateOptions,
  visaTypeOptions,
} from "../data/options";
import { ErrorBanner, SuccessBanner } from "../components/Status";

const steps = ["Contact", "Identity", "Disclosures", "Agreements"];

const initialContact = {
  email_address: "",
  phone_number: "",
  street_address: "",
  unit: "",
  city: "",
  state: "",
  postal_code: "",
  country: "USA",
};

const initialIdentity = {
  given_name: "",
  middle_name: "",
  family_name: "",
  date_of_birth: "",
  tax_id: "",
  tax_id_type: "USA_SSN",
  country_of_citizenship: "USA",
  country_of_birth: "USA",
  country_of_tax_residence: "USA",
  permanent_resident: "false",
  visa_type: "",
  visa_expiration_date: "",
  date_of_departure_from_usa: "",
  funding_source: "employment_income",
  annual_income_min: "",
  annual_income_max: "",
  liquid_net_worth_min: "",
  liquid_net_worth_max: "",
  total_net_worth_min: "",
  total_net_worth_max: "",
};

const initialDisclosures = {
  is_control_person: "false",
  is_affiliated_exchange_or_finra: "false",
  is_politically_exposed: "false",
  immediate_family_exposed: "false",
  employment_status: "EMPLOYED",
  employer_name: "",
  employer_address: "",
  employment_position: "",
};

const agreementOptions = [
  {
    value: "account_agreement",
    label: "Account Agreement",
    href: "https://files.alpaca.markets/disclosures/library/AcctAppMarginAndCustAgmt.pdf",
  },
  {
    value: "customer_agreement",
    label: "Customer Agreement",
    href: "https://files.alpaca.markets/disclosures/library/AcctAppMarginAndCustAgmt.pdf",
  },
  {
    value: "margin_agreement",
    label: "Margin Agreement",
    href: "https://files.alpaca.markets/disclosures/library/MarginDiscStmt.pdf",
  },
];

const cryptoAgreement = {
  value: "crypto_agreement",
  label: "Crypto Agreement",
  href: "https://files.alpaca.markets/disclosures/library/Crypto%20Customer%20Agreement.pdf",
};

const cryptoEligibleStateCodes = new Set([
  "AZ", "CA", "CT", "GA", "ID", "IL", "IN", "IA", "KS", "KY", "ME",
  "MD", "MA", "MI", "MS", "MO", "MT", "NE", "NC", "ND", "OH", "RI",
  "SC", "SD", "UT", "VT", "WA", "WV",
]);

function boolString(value) {
  return value === "true";
}

function Field({ label, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

export default function SignupPage({ onBackToLogin }) {
  const [step, setStep] = useState(0);
  const [contact, setContact] = useState(initialContact);
  const [identity, setIdentity] = useState(initialIdentity);
  const [disclosures, setDisclosures] = useState(initialDisclosures);
  const [accepted, setAccepted] = useState({});
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const shouldAskVisa = useMemo(() => {
    return identity.country_of_citizenship !== "USA" && identity.permanent_resident !== "true";
  }, [identity.country_of_citizenship, identity.permanent_resident]);

  const visibleAgreementOptions = useMemo(() => {
    const isCryptoEligible = contact.country === "USA" && cryptoEligibleStateCodes.has(contact.state);
    return isCryptoEligible ? [...agreementOptions, cryptoAgreement] : agreementOptions;
  }, [contact.country, contact.state]);

  function updateContact(field, value) {
    setContact((current) => ({ ...current, [field]: value }));
  }

  function updateIdentity(field, value) {
    setIdentity((current) => ({ ...current, [field]: value }));
  }

  function updateDisclosure(field, value) {
    setDisclosures((current) => ({ ...current, [field]: value }));
  }

  function next() {
    setError("");
    setStep((current) => Math.min(current + 1, steps.length - 1));
  }

  function back() {
    setError("");
    setStep((current) => Math.max(current - 1, 0));
  }

  async function submitSignup(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    if (!visibleAgreementOptions.every((agreement) => accepted[agreement.value])) {
      setError("Please accept every required agreement.");
      return;
    }

    const signedAt = new Date().toISOString();
    const identityPayload = {
      ...identity,
      permanent_resident: boolString(identity.permanent_resident),
      funding_source: [identity.funding_source],
    };

    if (!shouldAskVisa) {
      delete identityPayload.visa_type;
      delete identityPayload.visa_expiration_date;
      delete identityPayload.date_of_departure_from_usa;
    }

    try {
      setIsSubmitting(true);
      await apiRequest("/accounts/create-baskt-account", {
        method: "POST",
        body: JSON.stringify({
          contact: {
            ...contact,
            street_address: [contact.street_address],
            unit: contact.unit || undefined,
          },
          identity: identityPayload,
          disclosures: {
            ...disclosures,
            is_control_person: boolString(disclosures.is_control_person),
            is_affiliated_exchange_or_finra: boolString(disclosures.is_affiliated_exchange_or_finra),
            is_politically_exposed: boolString(disclosures.is_politically_exposed),
            immediate_family_exposed: boolString(disclosures.immediate_family_exposed),
          },
          agreements: visibleAgreementOptions.map((agreement) => ({
            agreement: agreement.value,
            signed_at: signedAt,
            ip_address: "127.0.0.1",
          })),
          password,
        }),
      });
      setSuccess("Account submitted successfully. You can now sign in.");
      window.setTimeout(onBackToLogin, 1000);
    } catch (signupError) {
      setError(signupError?.message || "Could not create your account.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="signup-page">
      <section className="signup-panel">
        <button className="text-button" type="button" onClick={onBackToLogin}>
          Back to sign in
        </button>
        <p className="eyebrow">Open your Baskt account</p>
        <h1>Onboarding that stays out of your way.</h1>
        <div className="stepper">
          {steps.map((label, index) => (
            <span key={label} className={index <= step ? "active" : ""}>
              {label}
            </span>
          ))}
        </div>
        <ErrorBanner message={error} />
        <SuccessBanner message={success} />

        <form className="signup-form" onSubmit={submitSignup}>
          {step === 0 ? (
            <div className="form-grid">
              <Field label="Email">
                <input type="email" value={contact.email_address} onChange={(e) => updateContact("email_address", e.target.value)} required />
              </Field>
              <Field label="Phone">
                <input value={contact.phone_number} onChange={(e) => updateContact("phone_number", e.target.value)} required />
              </Field>
              <Field label="Street address">
                <input value={contact.street_address} onChange={(e) => updateContact("street_address", e.target.value)} required />
              </Field>
              <Field label="Unit">
                <input value={contact.unit} onChange={(e) => updateContact("unit", e.target.value)} />
              </Field>
              <Field label="City">
                <input value={contact.city} onChange={(e) => updateContact("city", e.target.value)} required />
              </Field>
              <Field label="State">
                <select value={contact.state} onChange={(e) => updateContact("state", e.target.value)} required>
                  <option value="">Select</option>
                  {usStateOptions.map((state) => <option key={state} value={state}>{state}</option>)}
                </select>
              </Field>
              <Field label="Postal code">
                <input value={contact.postal_code} onChange={(e) => updateContact("postal_code", e.target.value)} required />
              </Field>
              <Field label="Country">
                <select value={contact.country} onChange={(e) => updateContact("country", e.target.value)} required>
                  {countryOptions.map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}
                </select>
              </Field>
            </div>
          ) : null}

          {step === 1 ? (
            <div className="form-grid">
              <Field label="First name"><input value={identity.given_name} onChange={(e) => updateIdentity("given_name", e.target.value)} required /></Field>
              <Field label="Middle name"><input value={identity.middle_name} onChange={(e) => updateIdentity("middle_name", e.target.value)} /></Field>
              <Field label="Last name"><input value={identity.family_name} onChange={(e) => updateIdentity("family_name", e.target.value)} required /></Field>
              <Field label="Date of birth"><input type="date" value={identity.date_of_birth} onChange={(e) => updateIdentity("date_of_birth", e.target.value)} required /></Field>
              <Field label="Tax ID"><input value={identity.tax_id} onChange={(e) => updateIdentity("tax_id", e.target.value)} required /></Field>
              <Field label="Tax ID type">
                <select value={identity.tax_id_type} onChange={(e) => updateIdentity("tax_id_type", e.target.value)} required>
                  {taxIdTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </Field>
              <Field label="Citizenship">
                <select value={identity.country_of_citizenship} onChange={(e) => updateIdentity("country_of_citizenship", e.target.value)} required>
                  {countryOptions.map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}
                </select>
              </Field>
              <Field label="Country of birth">
                <select value={identity.country_of_birth} onChange={(e) => updateIdentity("country_of_birth", e.target.value)} required>
                  {countryOptions.map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}
                </select>
              </Field>
              <Field label="Tax residence">
                <select value={identity.country_of_tax_residence} onChange={(e) => updateIdentity("country_of_tax_residence", e.target.value)} required>
                  {countryOptions.map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}
                </select>
              </Field>
              {identity.country_of_citizenship !== "USA" ? (
                <Field label="Green card holder">
                  <select value={identity.permanent_resident} onChange={(e) => updateIdentity("permanent_resident", e.target.value)} required>
                    <option value="true">Yes</option>
                    <option value="false">No</option>
                  </select>
                </Field>
              ) : null}
              {shouldAskVisa ? (
                <>
                  <Field label="Visa type">
                    <select value={identity.visa_type} onChange={(e) => updateIdentity("visa_type", e.target.value)} required>
                      <option value="">Select</option>
                      {visaTypeOptions.map((visa) => <option key={visa} value={visa}>{visa}</option>)}
                    </select>
                  </Field>
                  <Field label="Visa expiration"><input type="date" value={identity.visa_expiration_date} onChange={(e) => updateIdentity("visa_expiration_date", e.target.value)} required /></Field>
                  <Field label="Departure date"><input type="date" value={identity.date_of_departure_from_usa} onChange={(e) => updateIdentity("date_of_departure_from_usa", e.target.value)} required /></Field>
                </>
              ) : null}
              <Field label="Funding source">
                <select value={identity.funding_source} onChange={(e) => updateIdentity("funding_source", e.target.value)} required>
                  {fundingSourceOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </Field>
              <Field label="Annual income min"><input type="number" value={identity.annual_income_min} onChange={(e) => updateIdentity("annual_income_min", e.target.value)} required /></Field>
              <Field label="Annual income max"><input type="number" value={identity.annual_income_max} onChange={(e) => updateIdentity("annual_income_max", e.target.value)} required /></Field>
              <Field label="Liquid net worth min"><input type="number" value={identity.liquid_net_worth_min} onChange={(e) => updateIdentity("liquid_net_worth_min", e.target.value)} required /></Field>
              <Field label="Liquid net worth max"><input type="number" value={identity.liquid_net_worth_max} onChange={(e) => updateIdentity("liquid_net_worth_max", e.target.value)} required /></Field>
              <Field label="Total net worth min"><input type="number" value={identity.total_net_worth_min} onChange={(e) => updateIdentity("total_net_worth_min", e.target.value)} required /></Field>
              <Field label="Total net worth max"><input type="number" value={identity.total_net_worth_max} onChange={(e) => updateIdentity("total_net_worth_max", e.target.value)} required /></Field>
            </div>
          ) : null}

          {step === 2 ? (
            <div className="form-grid">
              {[
                ["is_control_person", "Control person"],
                ["is_affiliated_exchange_or_finra", "Affiliated with exchange or FINRA"],
                ["is_politically_exposed", "Politically exposed"],
                ["immediate_family_exposed", "Immediate family politically exposed"],
              ].map(([field, label]) => (
                <Field key={field} label={label}>
                  <select value={disclosures[field]} onChange={(e) => updateDisclosure(field, e.target.value)} required>
                    <option value="false">No</option>
                    <option value="true">Yes</option>
                  </select>
                </Field>
              ))}
              <Field label="Employment status">
                <select value={disclosures.employment_status} onChange={(e) => updateDisclosure("employment_status", e.target.value)} required>
                  {employmentStatusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </Field>
              {disclosures.employment_status === "EMPLOYED" ? (
                <>
                  <Field label="Employer"><input value={disclosures.employer_name} onChange={(e) => updateDisclosure("employer_name", e.target.value)} required /></Field>
                  <Field label="Employer address"><input value={disclosures.employer_address} onChange={(e) => updateDisclosure("employer_address", e.target.value)} required /></Field>
                  <Field label="Position"><input value={disclosures.employment_position} onChange={(e) => updateDisclosure("employment_position", e.target.value)} required /></Field>
                </>
              ) : null}
            </div>
          ) : null}

          {step === 3 ? (
            <div className="form-stack">
              <div className="agreement-list">
                {visibleAgreementOptions.map((agreement) => (
                  <label className="check-row" key={agreement.value}>
                    <input
                      type="checkbox"
                      checked={Boolean(accepted[agreement.value])}
                      onChange={(event) => setAccepted((current) => ({ ...current, [agreement.value]: event.target.checked }))}
                    />
                    <span>I agree to the <a href={agreement.href} target="_blank" rel="noreferrer">{agreement.label}</a></span>
                  </label>
                ))}
              </div>
              <div className="form-grid">
                <Field label="Password"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
                <Field label="Confirm password"><input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required /></Field>
              </div>
            </div>
          ) : null}

          <div className="form-actions">
            {step > 0 ? <button className="ghost-button" type="button" onClick={back}>Back</button> : null}
            {step < steps.length - 1 ? (
              <button className="primary-button" type="button" onClick={next}>Continue</button>
            ) : (
              <button className="primary-button" type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Submitting..." : "Create account"}
              </button>
            )}
          </div>
        </form>
      </section>
    </main>
  );
}
