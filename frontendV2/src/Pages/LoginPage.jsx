export default function LoginPage({
  email,
  password,
  setEmail,
  setPassword,
  onSubmit,
  forgotPasswordUrl,
  onShowSignUp,
  isSubmitting,
  statusMessage,
  errorMessage,
}) {
  return (
    <section className="login-card" aria-labelledby="login-title">
      <div className="title-row">
        <h1 id="login-title">Welcome to Baskt</h1>
        <img src="/BasktLogo.png" alt="Baskt logo" className="title-logo" />
      </div>
      <p className="subtitle">A better investing experience.</p>

      {statusMessage ? <p className="status-message">{statusMessage}</p> : null}
      {errorMessage ? <p className="error-message">{errorMessage}</p> : null}

      <form onSubmit={onSubmit} className="login-form">
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="name@company.com"
          autoComplete="email"
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Enter your password"
          autoComplete="current-password"
          required
        />

        <button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Signing in..." : "Log in"}
        </button>
      </form>

      <div className="aux-row">
        <a href={forgotPasswordUrl}>Forgot password?</a>
        <button type="button" className="link-button" onClick={onShowSignUp}>
          Create account
        </button>
      </div>
    </section>
  );
}
