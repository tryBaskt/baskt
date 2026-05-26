export default function SignUpPage({
  isConfirmStep,
  email,
  password,
  confirmPassword,
  verificationCode,
  pendingEmail,
  setEmail,
  setPassword,
  setConfirmPassword,
  setVerificationCode,
  setPendingEmail,
  onSignUpSubmit,
  onConfirmSubmit,
  onBackToLogin,
  forgotPasswordUrl,
  isSubmitting,
  statusMessage,
  errorMessage,
}) {
  return (
    <section className="login-card" aria-labelledby="signup-title">
      <p className="eyebrow">Baskt</p>
      <h1 id="signup-title">{isConfirmStep ? "Verify your email" : "Create account"}</h1>
      <p className="subtitle">
        {isConfirmStep
          ? "Enter the verification code sent to your email to finish sign up."
          : "Create your Baskt account with the same secure Cognito backend."}
      </p>

      {statusMessage ? <p className="status-message">{statusMessage}</p> : null}
      {errorMessage ? <p className="error-message">{errorMessage}</p> : null}

      {!isConfirmStep ? (
        <form onSubmit={onSignUpSubmit} className="login-form">
          <label htmlFor="signup-email">Email</label>
          <input
            id="signup-email"
            name="signup-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@company.com"
            autoComplete="email"
            required
          />

          <label htmlFor="signup-password">Password</label>
          <input
            id="signup-password"
            name="signup-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Create a strong password"
            autoComplete="new-password"
            required
          />

          <label htmlFor="signup-confirm-password">Confirm password</label>
          <input
            id="signup-confirm-password"
            name="signup-confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Re-enter your password"
            autoComplete="new-password"
            required
          />

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Creating..." : "Create account"}
          </button>
        </form>
      ) : (
        <form onSubmit={onConfirmSubmit} className="login-form">
          <label htmlFor="confirm-email">Email</label>
          <input
            id="confirm-email"
            name="confirm-email"
            type="email"
            value={pendingEmail}
            onChange={(e) => setPendingEmail(e.target.value)}
            autoComplete="email"
            required
          />

          <label htmlFor="verification-code">Verification code</label>
          <input
            id="verification-code"
            name="verification-code"
            type="text"
            value={verificationCode}
            onChange={(e) => setVerificationCode(e.target.value)}
            placeholder="Enter the code from email"
            required
          />

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Verifying..." : "Verify account"}
          </button>
        </form>
      )}

      <div className="aux-row">
        <a href={forgotPasswordUrl}>Forgot password?</a>
        <button type="button" className="link-button" onClick={onBackToLogin}>
          Back to login
        </button>
      </div>
    </section>
  );
}
