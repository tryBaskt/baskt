import { useState } from "react";

const defaultDisclosure = {
  is_control_person: "",
  is_affiliated_exchange_or_finra: "",
  is_politically_exposed: "",
  immediate_family_exposed: "",
  employment_status: "",
  employer_name: "",
  employer_address: "",
  employment_position: "",
};

const requiredDisclosureFields = [
  "is_control_person",
  "is_affiliated_exchange_or_finra",
  "is_politically_exposed",
  "immediate_family_exposed",
  "employment_status",
];

const employmentStatusOptions = [
  { value: "EMPLOYED", label: "Employed" },
  { value: "UNEMPLOYED", label: "Unemployed" },
  { value: "RETIRED", label: "Retired" },
  { value: "STUDENT", label: "Student" },
];

function parseBoolean(value) {
  return value === "true";
}

function stringValue(value) {
  if (value === undefined || value === null) {
    return "";
  }
  return String(value);
}

function HelpTooltip({ text }) {
  return (
    <span className="tooltip-wrapper">
      <button type="button" className="tooltip-trigger" aria-label={text}>
        ?
      </button>
      <span className="tooltip-content" role="tooltip">
        {text}
      </span>
    </span>
  );
}

export default function DisclosurePage({
  initialDisclosure,
  onDisclosureSubmit,
  onBackToIdentity,
  onBackToLogin,
  statusMessage,
  errorMessage,
}) {
  const [disclosure, setDisclosure] = useState({
    ...defaultDisclosure,
    ...initialDisclosure,
    is_control_person:
      typeof initialDisclosure?.is_control_person === "boolean"
        ? String(initialDisclosure.is_control_person)
        : initialDisclosure?.is_control_person || "",
    is_affiliated_exchange_or_finra:
      typeof initialDisclosure?.is_affiliated_exchange_or_finra === "boolean"
        ? String(initialDisclosure.is_affiliated_exchange_or_finra)
        : initialDisclosure?.is_affiliated_exchange_or_finra || "",
    is_politically_exposed:
      typeof initialDisclosure?.is_politically_exposed === "boolean"
        ? String(initialDisclosure.is_politically_exposed)
        : initialDisclosure?.is_politically_exposed || "",
    immediate_family_exposed:
      typeof initialDisclosure?.immediate_family_exposed === "boolean"
        ? String(initialDisclosure.immediate_family_exposed)
        : initialDisclosure?.immediate_family_exposed || "",
    employment_status: stringValue(initialDisclosure?.employment_status),
    employer_name: stringValue(initialDisclosure?.employer_name),
    employer_address: stringValue(initialDisclosure?.employer_address),
    employment_position: stringValue(initialDisclosure?.employment_position),
  });
  const [validationError, setValidationError] = useState("");
  const shouldAskEmployerDetails = disclosure.employment_status === "EMPLOYED";

  function updateDisclosure(fieldName, value) {
    setDisclosure((currentDisclosure) => ({
      ...currentDisclosure,
      [fieldName]: value,
    }));
  }

  function handleDisclosureSubmit(event) {
    event.preventDefault();
    setValidationError("");

    const trimmedDisclosure = {
      is_control_person: disclosure.is_control_person,
      is_affiliated_exchange_or_finra: disclosure.is_affiliated_exchange_or_finra,
      is_politically_exposed: disclosure.is_politically_exposed,
      immediate_family_exposed: disclosure.immediate_family_exposed,
      employment_status: stringValue(disclosure.employment_status).trim(),
      employer_name: stringValue(disclosure.employer_name).trim(),
      employer_address: stringValue(disclosure.employer_address).trim(),
      employment_position: stringValue(disclosure.employment_position).trim(),
    };

    const hasMissingRequiredField = requiredDisclosureFields.some(
      (fieldName) => trimmedDisclosure[fieldName] === ""
    );

    if (hasMissingRequiredField) {
      setValidationError("Please fill out every required disclosure field.");
      return;
    }

    if (
      shouldAskEmployerDetails &&
      (!trimmedDisclosure.employer_name ||
        !trimmedDisclosure.employer_address ||
        !trimmedDisclosure.employment_position)
    ) {
      setValidationError("Please fill out every required employment field.");
      return;
    }

    onDisclosureSubmit({
      is_control_person: parseBoolean(trimmedDisclosure.is_control_person),
      is_affiliated_exchange_or_finra: parseBoolean(
        trimmedDisclosure.is_affiliated_exchange_or_finra
      ),
      is_politically_exposed: parseBoolean(trimmedDisclosure.is_politically_exposed),
      immediate_family_exposed: parseBoolean(trimmedDisclosure.immediate_family_exposed),
      employment_status: trimmedDisclosure.employment_status,
      employer_name: shouldAskEmployerDetails ? trimmedDisclosure.employer_name : undefined,
      employer_address: shouldAskEmployerDetails ? trimmedDisclosure.employer_address : undefined,
      employment_position: shouldAskEmployerDetails ? trimmedDisclosure.employment_position : undefined,
    });
  }

  return (
    <section className="signup-card" aria-labelledby="signup-disclosure-title">
      <p className="eyebrow">Create account</p>
      <h1 id="signup-disclosure-title">Disclosure information</h1>
      <p className="subtitle">Answer the required regulatory disclosure questions for your account.</p>

      {statusMessage ? <p className="status-message">{statusMessage}</p> : null}
      {errorMessage ? <p className="error-message">{errorMessage}</p> : null}
      {validationError ? <p className="error-message">{validationError}</p> : null}

      <form onSubmit={handleDisclosureSubmit} className="signup-form">
        <div className="signup-form-grid">
          <div className="field-group">
            <label htmlFor="disclosure-control-person">
              Control person{" "}
              <HelpTooltip text="A person who is a director, officer, 10% shareholder, or otherwise controls a publicly traded company." />{" "}
              <span className="required-marker">*</span>
            </label>
            <select
              id="disclosure-control-person"
              value={disclosure.is_control_person}
              onChange={(event) => updateDisclosure("is_control_person", event.target.value)}
              required
            >
              <option value="">Select answer</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </div>

          <div className="field-group">
            <label htmlFor="disclosure-affiliated">
              Affiliated with exchange or FINRA{" "}
              <HelpTooltip text="You or an immediate family member works for, is registered with, or is associated with a securities exchange, FINRA, or a broker-dealer." />{" "}
              <span className="required-marker">*</span>
            </label>
            <select
              id="disclosure-affiliated"
              value={disclosure.is_affiliated_exchange_or_finra}
              onChange={(event) =>
                updateDisclosure("is_affiliated_exchange_or_finra", event.target.value)
              }
              required
            >
              <option value="">Select answer</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </div>

          <div className="field-group">
            <label htmlFor="disclosure-politically-exposed">
              Politically exposed{" "}
              <HelpTooltip text="A current or former senior political figure, government official, political party official, or close associate of one." />{" "}
              <span className="required-marker">*</span>
            </label>
            <select
              id="disclosure-politically-exposed"
              value={disclosure.is_politically_exposed}
              onChange={(event) => updateDisclosure("is_politically_exposed", event.target.value)}
              required
            >
              <option value="">Select answer</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </div>

          <div className="field-group">
            <label htmlFor="disclosure-family-exposed">
              Immediate family politically exposed{" "}
              <HelpTooltip text="An immediate family member is a current or former senior political figure, government official, political party official, or close associate of one." />{" "}
              <span className="required-marker">*</span>
            </label>
            <select
              id="disclosure-family-exposed"
              value={disclosure.immediate_family_exposed}
              onChange={(event) => updateDisclosure("immediate_family_exposed", event.target.value)}
              required
            >
              <option value="">Select answer</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </div>

          <div className="field-group">
            <label htmlFor="disclosure-employment-status">
              Employment status <span className="required-marker">*</span>
            </label>
            <select
              id="disclosure-employment-status"
              value={disclosure.employment_status}
              onChange={(event) => updateDisclosure("employment_status", event.target.value)}
              required
            >
              <option value="">Select status</option>
              {employmentStatusOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {shouldAskEmployerDetails ? (
            <>
              <div className="field-group">
                <label htmlFor="disclosure-employer-name">
                  Employer name <span className="required-marker">*</span>
                </label>
                <input
                  id="disclosure-employer-name"
                  type="text"
                  value={disclosure.employer_name}
                  onChange={(event) => updateDisclosure("employer_name", event.target.value)}
                  required
                />
              </div>

              <div className="field-group field-span">
                <label htmlFor="disclosure-employer-address">
                  Employer address <span className="required-marker">*</span>
                </label>
                <input
                  id="disclosure-employer-address"
                  type="text"
                  value={disclosure.employer_address}
                  onChange={(event) => updateDisclosure("employer_address", event.target.value)}
                  required
                />
              </div>

              <div className="field-group">
                <label htmlFor="disclosure-employment-position">
                  Employment position <span className="required-marker">*</span>
                </label>
                <input
                  id="disclosure-employment-position"
                  type="text"
                  value={disclosure.employment_position}
                  onChange={(event) => updateDisclosure("employment_position", event.target.value)}
                  required
                />
              </div>
            </>
          ) : null}
        </div>

        <div className="signup-actions">
          <button type="button" className="secondary-button login-return-button" onClick={onBackToLogin}>
            Back to Login
          </button>
          <button type="button" className="secondary-button" onClick={onBackToIdentity}>
            Back
          </button>
          <button type="submit">Continue</button>
        </div>
      </form>
    </section>
  );
}
