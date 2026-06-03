import { useState } from "react";

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

export default function AgreementPage({
  initialAgreements,
  password,
  confirmPassword,
  setPassword,
  setConfirmPassword,
  onAgreementSubmit,
  onBackToDisclosure,
  onBackToLogin,
  isSubmitting,
  statusMessage,
  errorMessage,
}) {
  const [acceptedAgreements, setAcceptedAgreements] = useState(() => {
    const acceptedValues = new Set(
      (initialAgreements || []).map((agreement) => agreement.agreement)
    );

    return agreementOptions.reduce(
      (accumulator, agreement) => ({
        ...accumulator,
        [agreement.value]: acceptedValues.has(agreement.value),
      }),
      {}
    );
  });
  const [validationError, setValidationError] = useState("");

  function updateAcceptedAgreement(agreementValue, checked) {
    setAcceptedAgreements((currentAcceptedAgreements) => ({
      ...currentAcceptedAgreements,
      [agreementValue]: checked,
    }));
  }

  function handleAgreementSubmit(event) {
    event.preventDefault();
    setValidationError("");

    const hasAcceptedAllAgreements = agreementOptions.every(
      (agreement) => acceptedAgreements[agreement.value]
    );

    if (!hasAcceptedAllAgreements) {
      setValidationError("Please review and accept every required agreement.");
      return;
    }

    if (!password || !confirmPassword) {
      setValidationError("Please enter and confirm your password.");
      return;
    }

    if (password !== confirmPassword) {
      setValidationError("Passwords do not match.");
      return;
    }

    const signedAt = new Date().toISOString();

    onAgreementSubmit({
      agreements: agreementOptions.map((agreement) => ({
        agreement: agreement.value,
        signed_at: signedAt,
        ip_address: "127.0.0.1",
      })),
      password,
    });
  }

  return (
    <section className="signup-card" aria-labelledby="signup-agreement-title">
      <p className="eyebrow">Create account</p>
      <h1 id="signup-agreement-title">Agreements</h1>
      <p className="subtitle">Review and accept the required agreements before creating your account.</p>

      {statusMessage ? <p className="status-message">{statusMessage}</p> : null}
      {errorMessage ? <p className="error-message">{errorMessage}</p> : null}
      {validationError ? <p className="error-message">{validationError}</p> : null}

      <form onSubmit={handleAgreementSubmit} className="signup-form">
        <div className="agreement-list">
          {agreementOptions.map((agreement) => (
            <label key={agreement.value} className="agreement-row">
              <input
                type="checkbox"
                checked={Boolean(acceptedAgreements[agreement.value])}
                onChange={(event) =>
                  updateAcceptedAgreement(agreement.value, event.target.checked)
                }
              />
              <span>
                I have reviewed and agree to the{" "}
                <a href={agreement.href} target="_blank" rel="noreferrer">
                  {agreement.label}
                </a>
                <span className="required-marker"> *</span>
              </span>
            </label>
          ))}
        </div>

        <div className="signup-form-grid">
          <div className="field-group">
            <label htmlFor="signup-password">
              Password <span className="required-marker">*</span>
            </label>
            <input
              id="signup-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="signup-confirm-password">
              Confirm password <span className="required-marker">*</span>
            </label>
            <input
              id="signup-confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
        </div>

        <div className="signup-actions">
          <button type="button" className="secondary-button login-return-button" onClick={onBackToLogin}>
            Back to Login
          </button>
          <button type="button" className="secondary-button" onClick={onBackToDisclosure}>
            Back
          </button>
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Submitting..." : "Submit"}
          </button>
        </div>
      </form>
    </section>
  );
}
