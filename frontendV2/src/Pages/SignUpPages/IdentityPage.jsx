import { useState } from "react";
import { countryOptions } from "./countryOptions";

const defaultIdentity = {
  given_name: "",
  middle_name: "",
  family_name: "",
  date_of_birth: "",
  tax_id: "",
  tax_id_type: "",
  country_of_citizenship: "",
  country_of_birth: "",
  country_of_tax_residence: "",
  permanent_resident: "",
  visa_type: "",
  visa_expiration_date: "",
  date_of_departure_from_usa: "",
  funding_source: [],
  funding_source_choice: "",
  annual_income_min: "",
  annual_income_max: "",
  liquid_net_worth_min: "",
  liquid_net_worth_max: "",
  total_net_worth_min: "",
  total_net_worth_max: "",
};

const requiredIdentityFields = [
  "given_name",
  "family_name",
  "date_of_birth",
  "tax_id",
  "tax_id_type",
  "country_of_citizenship",
  "country_of_birth",
  "country_of_tax_residence",
  "funding_source",
  "annual_income_min",
  "annual_income_max",
  "liquid_net_worth_min",
  "liquid_net_worth_max",
  "total_net_worth_min",
  "total_net_worth_max",
];

const taxIdTypeOptions = [
  { value: "USA_SSN", label: "United States SSN" },
  { value: "USA_ITIN", label: "United States ITIN" },
  { value: "ARG_AR_CUIT", label: "Argentina CUIT" },
  { value: "AUS_TFN", label: "Australia TFN" },
  { value: "AUS_ABN", label: "Australia ABN" },
  { value: "BOL_NIT", label: "Bolivia NIT" },
  { value: "BRA_CPF", label: "Brazil CPF" },
  { value: "CHL_RUT", label: "Chile RUT" },
  { value: "COL_NIT", label: "Colombia NIT" },
  { value: "CRI_NITE", label: "Costa Rica NITE" },
  { value: "DEU_TAX_ID", label: "Germany Tax ID" },
  { value: "DOM_RNC", label: "Dominican Republic RNC" },
  { value: "ECU_RUC", label: "Ecuador RUC" },
  { value: "FRA_SPI", label: "France SPI" },
  { value: "GBR_UTR", label: "United Kingdom UTR" },
  { value: "GBR_NINO", label: "United Kingdom NINO" },
  { value: "GTM_NIT", label: "Guatemala NIT" },
  { value: "HND_RTN", label: "Honduras RTN" },
  { value: "HUN_TIN", label: "Hungary TIN" },
  { value: "IDN_KTP", label: "Indonesia KTP" },
  { value: "IND_PAN", label: "India PAN" },
  { value: "ISR_TAX_ID", label: "Israel Tax ID" },
  { value: "ITA_TAX_ID", label: "Italy Tax ID" },
  { value: "JPN_TAX_ID", label: "Japan Tax ID" },
  { value: "MEX_RFC", label: "Mexico RFC" },
  { value: "NIC_RUC", label: "Nicaragua RUC" },
  { value: "NLD_TIN", label: "Netherlands TIN" },
  { value: "PAN_RUC", label: "Panama RUC" },
  { value: "PER_RUC", label: "Peru RUC" },
  { value: "PRY_RUC", label: "Paraguay RUC" },
  { value: "SGP_NRIC", label: "Singapore NRIC" },
  { value: "SGP_FIN", label: "Singapore FIN" },
  { value: "SGP_ASGD", label: "Singapore ASGD" },
  { value: "SGP_ITR", label: "Singapore ITR" },
  { value: "SLV_NIT", label: "El Salvador NIT" },
  { value: "SWE_TAX_ID", label: "Sweden Tax ID" },
  { value: "URY_RUT", label: "Uruguay RUT" },
  { value: "VEN_RIF", label: "Venezuela RIF" },
  { value: "NATIONAL_ID", label: "National ID" },
  { value: "PASSPORT", label: "Passport" },
  { value: "PERMANENT_RESIDENT", label: "Permanent resident card" },
  { value: "DRIVER_LICENSE", label: "Driver license" },
  { value: "OTHER_GOV_ID", label: "Other government ID" },
  { value: "NOT_SPECIFIED", label: "Not specified" },
];

const visaTypeOptions = [
  { value: "B1", label: "B1" },
  { value: "B2", label: "B2" },
  { value: "DACA", label: "DACA" },
  { value: "E1", label: "E1" },
  { value: "E2", label: "E2" },
  { value: "E3", label: "E3" },
  { value: "F1", label: "F1" },
  { value: "G4", label: "G4" },
  { value: "H1B", label: "H1B" },
  { value: "J1", label: "J1" },
  { value: "L1", label: "L1" },
  { value: "O1", label: "O1" },
  { value: "TN1", label: "TN1" },
  { value: "OTHER", label: "Other" },
];

const fundingSourceOptions = [
  { value: "employment_income", label: "Employment income" },
  { value: "investments", label: "Investments" },
  { value: "inheritance", label: "Inheritance" },
  { value: "business_income", label: "Business income" },
  { value: "savings", label: "Savings" },
  { value: "family", label: "Family" },
];

function stringValue(value) {
  if (value === undefined || value === null) {
    return "";
  }
  return String(value);
}

function normalizeFundingSources(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean).map((source) => String(source));
  }

  if (value) {
    return [String(value)];
  }

  return [];
}

export default function IdentityPage({
  contactCountry,
  initialIdentity,
  onIdentitySubmit,
  onBackToContact,
  onBackToLogin,
  statusMessage,
  errorMessage,
}) {
  const [identity, setIdentity] = useState({
    ...defaultIdentity,
    ...initialIdentity,
    given_name: stringValue(initialIdentity?.given_name),
    middle_name: stringValue(initialIdentity?.middle_name),
    family_name: stringValue(initialIdentity?.family_name),
    date_of_birth: stringValue(initialIdentity?.date_of_birth),
    tax_id: stringValue(initialIdentity?.tax_id),
    tax_id_type: stringValue(initialIdentity?.tax_id_type),
    country_of_citizenship: stringValue(initialIdentity?.country_of_citizenship),
    country_of_birth: stringValue(initialIdentity?.country_of_birth),
    country_of_tax_residence: stringValue(initialIdentity?.country_of_tax_residence),
    permanent_resident:
      typeof initialIdentity?.permanent_resident === "boolean"
        ? String(initialIdentity.permanent_resident)
        : stringValue(initialIdentity?.permanent_resident),
    visa_type: stringValue(initialIdentity?.visa_type),
    visa_expiration_date: stringValue(initialIdentity?.visa_expiration_date),
    date_of_departure_from_usa: stringValue(initialIdentity?.date_of_departure_from_usa),
    funding_source: normalizeFundingSources(initialIdentity?.funding_source),
    funding_source_choice: "",
    annual_income_min: stringValue(initialIdentity?.annual_income_min),
    annual_income_max: stringValue(initialIdentity?.annual_income_max),
    liquid_net_worth_min: stringValue(initialIdentity?.liquid_net_worth_min),
    liquid_net_worth_max: stringValue(initialIdentity?.liquid_net_worth_max),
    total_net_worth_min: stringValue(initialIdentity?.total_net_worth_min),
    total_net_worth_max: stringValue(initialIdentity?.total_net_worth_max),
  });
  const [validationError, setValidationError] = useState("");
  const normalizedCitizenship = identity.country_of_citizenship.trim().toUpperCase();
  const normalizedContactCountry = contactCountry?.trim().toUpperCase() || "";
  const shouldAskPermanentResident = Boolean(normalizedCitizenship) && normalizedCitizenship !== "USA";
  const shouldAskVisaFields =
    shouldAskPermanentResident &&
    identity.permanent_resident === "false" &&
    normalizedContactCountry === "USA";

  function updateIdentity(fieldName, value) {
    setIdentity((currentIdentity) => ({
      ...currentIdentity,
      [fieldName]: value,
    }));
  }

  function addFundingSource() {
    const nextFundingSource = identity.funding_source_choice;
    if (!nextFundingSource || identity.funding_source.includes(nextFundingSource)) {
      return;
    }

    setIdentity((currentIdentity) => ({
      ...currentIdentity,
      funding_source: [...currentIdentity.funding_source, nextFundingSource],
      funding_source_choice: "",
    }));
  }

  function removeFundingSource(fundingSource) {
    setIdentity((currentIdentity) => ({
      ...currentIdentity,
      funding_source: currentIdentity.funding_source.filter(
        (currentFundingSource) => currentFundingSource !== fundingSource
      ),
    }));
  }

  function handleIdentitySubmit(event) {
    event.preventDefault();
    setValidationError("");

    const trimmedIdentity = {
      given_name: stringValue(identity.given_name).trim(),
      middle_name: stringValue(identity.middle_name).trim(),
      family_name: stringValue(identity.family_name).trim(),
      date_of_birth: stringValue(identity.date_of_birth).trim(),
      tax_id: stringValue(identity.tax_id).trim(),
      tax_id_type: stringValue(identity.tax_id_type).trim(),
      country_of_citizenship: stringValue(identity.country_of_citizenship).trim(),
      country_of_birth: stringValue(identity.country_of_birth).trim(),
      country_of_tax_residence: stringValue(identity.country_of_tax_residence).trim(),
      permanent_resident: stringValue(identity.permanent_resident).trim(),
      visa_type: stringValue(identity.visa_type).trim(),
      visa_expiration_date: stringValue(identity.visa_expiration_date).trim(),
      date_of_departure_from_usa: stringValue(identity.date_of_departure_from_usa).trim(),
      funding_source: normalizeFundingSources(identity.funding_source),
      annual_income_min: stringValue(identity.annual_income_min).trim(),
      annual_income_max: stringValue(identity.annual_income_max).trim(),
      liquid_net_worth_min: stringValue(identity.liquid_net_worth_min).trim(),
      liquid_net_worth_max: stringValue(identity.liquid_net_worth_max).trim(),
      total_net_worth_min: stringValue(identity.total_net_worth_min).trim(),
      total_net_worth_max: stringValue(identity.total_net_worth_max).trim(),
    };

    const hasMissingRequiredField = requiredIdentityFields.some(
      (fieldName) =>
        fieldName === "funding_source"
          ? trimmedIdentity.funding_source.length === 0
          : !trimmedIdentity[fieldName]
    );

    if (hasMissingRequiredField) {
      setValidationError("Please fill out every required identity field.");
      return;
    }

    if (shouldAskPermanentResident && !trimmedIdentity.permanent_resident) {
      setValidationError("Please indicate whether you are a U.S. permanent resident.");
      return;
    }

    if (
      shouldAskVisaFields &&
      (!trimmedIdentity.visa_type ||
        !trimmedIdentity.visa_expiration_date ||
        !trimmedIdentity.date_of_departure_from_usa)
    ) {
      setValidationError("Please fill out every required visa field.");
      return;
    }

    onIdentitySubmit({
      ...trimmedIdentity,
      middle_name: trimmedIdentity.middle_name || undefined,
      permanent_resident: shouldAskPermanentResident
        ? trimmedIdentity.permanent_resident === "true"
        : undefined,
      visa_type: shouldAskVisaFields ? trimmedIdentity.visa_type : undefined,
      visa_expiration_date: shouldAskVisaFields ? trimmedIdentity.visa_expiration_date : undefined,
      date_of_departure_from_usa: shouldAskVisaFields
        ? trimmedIdentity.date_of_departure_from_usa
        : undefined,
      funding_source: trimmedIdentity.funding_source,
      annual_income_min: Number(trimmedIdentity.annual_income_min),
      annual_income_max: Number(trimmedIdentity.annual_income_max),
      liquid_net_worth_min: Number(trimmedIdentity.liquid_net_worth_min),
      liquid_net_worth_max: Number(trimmedIdentity.liquid_net_worth_max),
      total_net_worth_min: Number(trimmedIdentity.total_net_worth_min),
      total_net_worth_max: Number(trimmedIdentity.total_net_worth_max),
    });
  }

  return (
    <section className="signup-card" aria-labelledby="signup-identity-title">
      <p className="eyebrow">Create account</p>
      <h1 id="signup-identity-title">Identity information</h1>
      <p className="subtitle">Provide the identity details required for your trading account application.</p>

      {statusMessage ? <p className="status-message">{statusMessage}</p> : null}
      {errorMessage ? <p className="error-message">{errorMessage}</p> : null}
      {validationError ? <p className="error-message">{validationError}</p> : null}

      <form onSubmit={handleIdentitySubmit} className="signup-form">
        <div className="signup-form-grid">
          <div className="field-group">
            <label htmlFor="identity-given-name">
              Given name <span className="required-marker">*</span>
            </label>
            <input
              id="identity-given-name"
              type="text"
              value={identity.given_name}
              onChange={(event) => updateIdentity("given_name", event.target.value)}
              autoComplete="given-name"
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-middle-name">Middle name</label>
            <input
              id="identity-middle-name"
              type="text"
              value={identity.middle_name}
              onChange={(event) => updateIdentity("middle_name", event.target.value)}
              autoComplete="additional-name"
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-family-name">
              Family name <span className="required-marker">*</span>
            </label>
            <input
              id="identity-family-name"
              type="text"
              value={identity.family_name}
              onChange={(event) => updateIdentity("family_name", event.target.value)}
              autoComplete="family-name"
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-date-of-birth">
              Date of birth <span className="required-marker">*</span>
            </label>
            <input
              id="identity-date-of-birth"
              type="date"
              value={identity.date_of_birth}
              onChange={(event) => updateIdentity("date_of_birth", event.target.value)}
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-tax-id-type">
              Tax ID type <span className="required-marker">*</span>
            </label>
            <select
              id="identity-tax-id-type"
              value={identity.tax_id_type}
              onChange={(event) => updateIdentity("tax_id_type", event.target.value)}
              required
            >
              <option value="">Select tax ID type</option>
              {taxIdTypeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="field-group">
            <label htmlFor="identity-tax-id">
              Tax ID <span className="required-marker">*</span>
            </label>
            <input
              id="identity-tax-id"
              type="text"
              value={identity.tax_id}
              onChange={(event) => updateIdentity("tax_id", event.target.value)}
              required
            />
          </div>

            <div className="field-group">
              <label htmlFor="identity-citizenship">
                Country of citizenship <span className="required-marker">*</span>
              </label>
              <select
                id="identity-citizenship"
                value={identity.country_of_citizenship}
                onChange={(event) => updateIdentity("country_of_citizenship", event.target.value)}
                required
              >
                <option value="">Select country</option>
                {countryOptions.map((country) => (
                  <option key={country.value} value={country.value}>
                    {country.label} ({country.value})
                  </option>
                ))}
              </select>
            </div>

            <div className="field-group">
              <label htmlFor="identity-country-of-birth">
                Country of birth <span className="required-marker">*</span>
              </label>
              <select
                id="identity-country-of-birth"
                value={identity.country_of_birth}
                onChange={(event) => updateIdentity("country_of_birth", event.target.value)}
                required
              >
                <option value="">Select country</option>
                {countryOptions.map((country) => (
                  <option key={country.value} value={country.value}>
                    {country.label} ({country.value})
                  </option>
                ))}
              </select>
            </div>

            <div className="field-group">
              <label htmlFor="identity-tax-residence">
                Country of tax residence <span className="required-marker">*</span>
              </label>
              <select
                id="identity-tax-residence"
                value={identity.country_of_tax_residence}
                onChange={(event) => updateIdentity("country_of_tax_residence", event.target.value)}
                required
              >
                <option value="">Select country</option>
                {countryOptions.map((country) => (
                  <option key={country.value} value={country.value}>
                    {country.label} ({country.value})
                  </option>
                ))}
              </select>
            </div>

          {shouldAskPermanentResident ? (
            <div className="field-group">
              <label htmlFor="identity-permanent-resident">
                U.S. permanent resident <span className="required-marker">*</span>
              </label>
              <select
                id="identity-permanent-resident"
                value={identity.permanent_resident}
                onChange={(event) => updateIdentity("permanent_resident", event.target.value)}
                required
              >
                <option value="">Select status</option>
                <option value="true">Yes</option>
                <option value="false">No</option>
              </select>
            </div>
          ) : null}

          {shouldAskVisaFields ? (
            <>
              <div className="field-group">
                <label htmlFor="identity-visa-type">
                  Visa type <span className="required-marker">*</span>
                </label>
                <select
                  id="identity-visa-type"
                  value={identity.visa_type}
                  onChange={(event) => updateIdentity("visa_type", event.target.value)}
                  required
                >
                  <option value="">Select visa type</option>
                  {visaTypeOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field-group">
                <label htmlFor="identity-visa-expiration">
                  Visa expiration date <span className="required-marker">*</span>
                </label>
                <input
                  id="identity-visa-expiration"
                  type="date"
                  value={identity.visa_expiration_date}
                  onChange={(event) => updateIdentity("visa_expiration_date", event.target.value)}
                  required
                />
              </div>

              <div className="field-group">
                <label htmlFor="identity-departure-date">
                  Date of departure from U.S. <span className="required-marker">*</span>
                </label>
                <input
                  id="identity-departure-date"
                  type="date"
                  value={identity.date_of_departure_from_usa}
                  onChange={(event) => updateIdentity("date_of_departure_from_usa", event.target.value)}
                  required
                />
              </div>
            </>
          ) : null}

          <div className="field-group">
            <label htmlFor="identity-funding-source">
              Funding source <span className="required-marker">*</span>
            </label>
            <div className="appendable-select-row">
              <select
                id="identity-funding-source"
                value={identity.funding_source_choice}
                onChange={(event) => updateIdentity("funding_source_choice", event.target.value)}
              >
                <option value="">Select funding source</option>
                {fundingSourceOptions
                  .filter((option) => !identity.funding_source.includes(option.value))
                  .map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                className="secondary-button appendable-add-button"
                onClick={addFundingSource}
                disabled={!identity.funding_source_choice}
              >
                Add
              </button>
            </div>
            {identity.funding_source.length > 0 ? (
              <div className="selected-pill-list" aria-label="Selected funding sources">
                {identity.funding_source.map((source) => {
                  const option = fundingSourceOptions.find(
                    (fundingSourceOption) => fundingSourceOption.value === source
                  );

                  return (
                    <span key={source} className="selected-pill">
                      {option?.label || source}
                      <button
                        type="button"
                        aria-label={`Remove ${option?.label || source}`}
                        onClick={() => removeFundingSource(source)}
                      >
                        x
                      </button>
                    </span>
                  );
                })}
              </div>
            ) : null}
          </div>

          <div className="field-group">
            <label htmlFor="identity-annual-income-min">
              Annual income min <span className="required-marker">*</span>
            </label>
            <input
              id="identity-annual-income-min"
              type="number"
              min="0"
              value={identity.annual_income_min}
              onChange={(event) => updateIdentity("annual_income_min", event.target.value)}
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-annual-income-max">
              Annual income max <span className="required-marker">*</span>
            </label>
            <input
              id="identity-annual-income-max"
              type="number"
              min="0"
              value={identity.annual_income_max}
              onChange={(event) => updateIdentity("annual_income_max", event.target.value)}
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-liquid-net-worth-min">
              Liquid net worth min <span className="required-marker">*</span>
            </label>
            <input
              id="identity-liquid-net-worth-min"
              type="number"
              min="0"
              value={identity.liquid_net_worth_min}
              onChange={(event) => updateIdentity("liquid_net_worth_min", event.target.value)}
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-liquid-net-worth-max">
              Liquid net worth max <span className="required-marker">*</span>
            </label>
            <input
              id="identity-liquid-net-worth-max"
              type="number"
              min="0"
              value={identity.liquid_net_worth_max}
              onChange={(event) => updateIdentity("liquid_net_worth_max", event.target.value)}
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-total-net-worth-min">
              Total net worth min <span className="required-marker">*</span>
            </label>
            <input
              id="identity-total-net-worth-min"
              type="number"
              min="0"
              value={identity.total_net_worth_min}
              onChange={(event) => updateIdentity("total_net_worth_min", event.target.value)}
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="identity-total-net-worth-max">
              Total net worth max <span className="required-marker">*</span>
            </label>
            <input
              id="identity-total-net-worth-max"
              type="number"
              min="0"
              value={identity.total_net_worth_max}
              onChange={(event) => updateIdentity("total_net_worth_max", event.target.value)}
              required
            />
          </div>
        </div>

        <div className="signup-actions">
          <button type="button" className="secondary-button login-return-button" onClick={onBackToLogin}>
            Back to Login
          </button>
          <button type="button" className="secondary-button" onClick={onBackToContact}>
            Back
          </button>
          <button type="submit">Continue</button>
        </div>
      </form>
    </section>
  );
}
