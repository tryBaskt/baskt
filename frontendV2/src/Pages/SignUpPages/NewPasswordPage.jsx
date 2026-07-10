import { useState } from "react";

export default function NewPasswordPage({
  email,
  newPassword,
  confirmNewPassword,
  setNewPassword,
  setConfirmNewPassword,
  onNewPasswordSubmit,
  onBackToLogin,
  isSubmitting,
  statusMessage,
  errorMessage,
}) {
  const [validationError, setValidationError] = useState("");

  function handleNewPasswordSubmit(event) {
    event.preventDefault();
    setValidationError("");

    if (!newPassword || !confirmNewPassword) {
      setValidationError("Please enter and confirm your new password.");
      return;
    }

    if (newPassword !== confirmNewPassword) {
      setValidationError("Passwords do not match.");
      return;
    }

    onNewPasswordSubmit();
  }

  return (
    <section className="signup-card" aria-labelledby="new-password-title">
      <h1 id="new-password-title">Set new password</h1>
      <p className="subtitle">Create a permanent password before signing in to Baskt.</p>

      {statusMessage ? <p className="status-message">{statusMessage}</p> : null}
      {errorMessage ? <p className="error-message">{errorMessage}</p> : null}
      {validationError ? <p className="error-message">{validationError}</p> : null}

      <form onSubmit={handleNewPasswordSubmit} className="signup-form">
        <div className="signup-form-grid">
          <div className="field-group field-span">
            <label htmlFor="new-password-email">Email</label>
            <input id="new-password-email" type="email" value={email} readOnly />
          </div>

          <div className="field-group">
            <label htmlFor="new-password">
              New password <span className="required-marker">*</span>
            </label>
            <input
              id="new-password"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
          </div>

          <div className="field-group">
            <label htmlFor="confirm-new-password">
              Confirm new password <span className="required-marker">*</span>
            </label>
            <input
              id="confirm-new-password"
              type="password"
              value={confirmNewPassword}
              onChange={(event) => setConfirmNewPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
        </div>

        <div className="signup-actions">
          <button type="button" className="secondary-button login-return-button" onClick={onBackToLogin}>
            Back to Login
          </button>
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving..." : "Save password"}
          </button>
        </div>
      </form>
    </section>
  );
}
