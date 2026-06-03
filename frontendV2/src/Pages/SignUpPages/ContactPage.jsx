import { useEffect, useState } from "react";
import { countryOptions } from "./countryOptions";
import { usStateOptions } from "./stateOptions";

const defaultContact = {
  email_address: "",
  phone_number: "",
  street_address: "",
  unit: "",
  city: "",
  state: "",
  postal_code: "",
  country: "",
};

const requiredContactFields = [
  "email_address",
  "phone_number",
  "street_address",
  "city",
  "state",
  "postal_code",
  "country",
];

const SMARTY_EMBEDDED_KEY = import.meta.env.VITE_SMARTY_EMBEDDED_KEY || "";
const SMARTY_AUTOCOMPLETE_URL = "https://us-autocomplete.api.smarty.com/v2/lookup";

export default function ContactPage({
  initialContact,
  onContactSubmit,
  onBackToLogin,
  statusMessage,
  errorMessage,
}) {
  const [contact, setContact] = useState({
    ...defaultContact,
    ...initialContact,
    street_address: initialContact?.street_address?.[0] || initialContact?.street_address || "",
  });
  const [validationError, setValidationError] = useState("");
  const [addressSuggestions, setAddressSuggestions] = useState([]);
  const [isAddressLoading, setIsAddressLoading] = useState(false);
  const [addressSearchError, setAddressSearchError] = useState("");
  const [isAddressDropdownOpen, setIsAddressDropdownOpen] = useState(false);

  useEffect(() => {
    const search = contact.street_address.trim();

    if (!SMARTY_EMBEDDED_KEY || search.length < 3) {
      setAddressSuggestions([]);
      setIsAddressLoading(false);
      setAddressSearchError("");
      return undefined;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(async () => {
      const params = new URLSearchParams({
        key: SMARTY_EMBEDDED_KEY,
        search,
        max_results: "6",
        include_only_states: "ALLSTATES",
      });

      try {
        setIsAddressLoading(true);
        setAddressSearchError("");
        const response = await fetch(`${SMARTY_AUTOCOMPLETE_URL}?${params.toString()}`, {
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error("Address lookup failed.");
        }

        const data = await response.json();
        setAddressSuggestions(data.suggestions || []);
        setIsAddressDropdownOpen(true);
      } catch (error) {
        if (error.name !== "AbortError") {
          setAddressSuggestions([]);
          setAddressSearchError("Address suggestions are temporarily unavailable.");
        }
      } finally {
        setIsAddressLoading(false);
      }
    }, 250);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [contact.street_address]);

  function updateContact(fieldName, value) {
    setContact((currentContact) => ({
      ...currentContact,
      [fieldName]: value,
    }));
  }

  function updateCountry(value) {
    setContact((currentContact) => ({
      ...currentContact,
      country: value,
      state: value === currentContact.country ? currentContact.state : "",
    }));
  }

  function selectAddressSuggestion(suggestion) {
    setContact((currentContact) => ({
      ...currentContact,
      street_address: suggestion.street_line || "",
      unit: suggestion.secondary || currentContact.unit,
      city: suggestion.city || "",
      state: suggestion.state || "",
      postal_code: suggestion.zipcode || "",
      country: "USA",
    }));
    setAddressSuggestions([]);
    setIsAddressDropdownOpen(false);
    setAddressSearchError("");
  }

  function handleContactSubmit(event) {
    event.preventDefault();
    setValidationError("");

    const trimmedContact = {
      email_address: contact.email_address.trim(),
      phone_number: contact.phone_number.trim(),
      street_address: contact.street_address.trim(),
      unit: contact.unit.trim(),
      city: contact.city.trim(),
      state: contact.state.trim(),
      postal_code: contact.postal_code.trim(),
      country: contact.country.trim(),
    };

    const hasMissingRequiredField = requiredContactFields.some(
      (fieldName) => !trimmedContact[fieldName]
    );

    if (hasMissingRequiredField) {
      setValidationError("Please fill out every required contact field.");
      return;
    }

    onContactSubmit({
      email_address: trimmedContact.email_address,
      phone_number: trimmedContact.phone_number,
      street_address: [trimmedContact.street_address],
      unit: trimmedContact.unit || undefined,
      city: trimmedContact.city,
      state: trimmedContact.state,
      postal_code: trimmedContact.postal_code,
      country: trimmedContact.country,
    });
  }

  return (
    <section className="signup-card" aria-labelledby="signup-contact-title">
      <p className="eyebrow">Create account</p>
      <h1 id="signup-contact-title">Contact information</h1>
      <p className="subtitle">Enter the contact details required to open your Baskt trading account.</p>

      {statusMessage ? <p className="status-message">{statusMessage}</p> : null}
      {errorMessage ? <p className="error-message">{errorMessage}</p> : null}
      {validationError ? <p className="error-message">{validationError}</p> : null}

      <form onSubmit={handleContactSubmit} className="signup-form">
        <div className="signup-form-grid">
          <div className="field-group">
            <label htmlFor="contact-email">
              Email <span className="required-marker">*</span>
            </label>
            <input
              id="contact-email"
              type="email"
              value={contact.email_address}
              onChange={(event) => updateContact("email_address", event.target.value)}
              autoComplete="email"
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="contact-phone">
              Phone number <span className="required-marker">*</span>
            </label>
            <input
              id="contact-phone"
              type="tel"
              value={contact.phone_number}
              onChange={(event) => updateContact("phone_number", event.target.value)}
              autoComplete="tel"
              required
            />
          </div>

          <div className="field-group field-span">
            <label htmlFor="contact-street">
              Street address <span className="required-marker">*</span>
            </label>
            <div className="address-autocomplete">
              <input
                id="contact-street"
                type="text"
                value={contact.street_address}
                onChange={(event) => {
                  updateContact("street_address", event.target.value);
                  setIsAddressDropdownOpen(true);
                }}
                onFocus={() => setIsAddressDropdownOpen(true)}
                autoComplete="address-line1"
                required
              />
              {isAddressDropdownOpen && addressSuggestions.length > 0 ? (
                <div className="address-suggestions" role="listbox" aria-label="Address suggestions">
                  {addressSuggestions.map((suggestion) => {
                    const suggestionKey = [
                      suggestion.street_line,
                      suggestion.secondary,
                      suggestion.city,
                      suggestion.state,
                      suggestion.zipcode,
                    ]
                      .filter(Boolean)
                      .join("-");

                    return (
                      <button
                        key={suggestionKey}
                        type="button"
                        className="address-suggestion"
                        onClick={() => selectAddressSuggestion(suggestion)}
                      >
                        <span>{suggestion.street_line}</span>
                        <small>
                          {[suggestion.secondary, suggestion.city, suggestion.state, suggestion.zipcode]
                            .filter(Boolean)
                            .join(", ")}
                        </small>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
            {isAddressLoading ? <p className="field-hint">Searching addresses...</p> : null}
            {addressSearchError ? <p className="field-error">{addressSearchError}</p> : null}
          </div>

          <div className="field-group">
            <label htmlFor="contact-unit">Unit</label>
            <input
              id="contact-unit"
              type="text"
              value={contact.unit}
              onChange={(event) => updateContact("unit", event.target.value)}
              autoComplete="address-line2"
            />
          </div>

          <div className="field-group">
            <label htmlFor="contact-city">
              City <span className="required-marker">*</span>
            </label>
            <input
              id="contact-city"
              type="text"
              value={contact.city}
              onChange={(event) => updateContact("city", event.target.value)}
              autoComplete="address-level2"
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="contact-country">
              Country <span className="required-marker">*</span>
            </label>
            <select
              id="contact-country"
              value={contact.country}
              onChange={(event) => updateCountry(event.target.value)}
              autoComplete="country"
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
            <label htmlFor="contact-state">
              State <span className="required-marker">*</span>
            </label>
            {contact.country === "USA" ? (
              <select
                id="contact-state"
                value={contact.state}
                onChange={(event) => updateContact("state", event.target.value)}
                autoComplete="address-level1"
                required
              >
                <option value="">Select state</option>
                {usStateOptions.map((state) => (
                  <option key={state.value} value={state.value}>
                    {state.label} ({state.value})
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="contact-state"
                type="text"
                value={contact.state}
                onChange={(event) => updateContact("state", event.target.value.toUpperCase())}
                autoComplete="address-level1"
                required
              />
            )}
          </div>

          <div className="field-group">
            <label htmlFor="contact-postal-code">
              Postal code <span className="required-marker">*</span>
            </label>
            <input
              id="contact-postal-code"
              type="text"
              value={contact.postal_code}
              onChange={(event) => updateContact("postal_code", event.target.value)}
              autoComplete="postal-code"
              required
            />
          </div>
        </div>

        <div className="signup-actions">
          <button type="button" className="secondary-button" onClick={onBackToLogin}>
            Back
          </button>
          <button type="submit">Continue</button>
        </div>
      </form>
    </section>
  );
}
