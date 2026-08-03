import { useState } from "react";
import { completeNewPassword, signIn } from "../lib/cognitoAuth";
import { saveSession } from "../lib/session";
import { ErrorBanner, SuccessBanner } from "../components/Status";

export default function LoginPage({ onAuthenticated, onShowSignup, forgotPasswordUrl }) {
  const [email, setEmail] = useState(() => localStorage.getItem("baskt.v3.lastEmail") || "");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [challenge, setChallenge] = useState(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submitLogin(event) {
    event.preventDefault();
    setError("");
    setSuccess("");

    try {
      setIsSubmitting(true);
      const tokens = await signIn(email.trim(), password);
      saveSession(tokens);
      localStorage.setItem("baskt.v3.lastEmail", email.trim());
      onAuthenticated();
    } catch (loginError) {
      if (loginError?.name === "NewPasswordRequired") {
        setChallenge(loginError);
        setPassword("");
        return;
      }
      setError(loginError?.message || "Sign in failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitNewPassword(event) {
    event.preventDefault();
    setError("");

    try {
      setIsSubmitting(true);
      const tokens = await completeNewPassword(
        challenge.cognitoUser,
        newPassword,
        challenge.userAttributes
      );
      saveSession(tokens);
      onAuthenticated();
    } catch (newPasswordError) {
      setError(newPasswordError?.message || "Could not set the new password.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-hero">
        <div className="brand-lockup static">
          <span className="brand-mark">
            <img src="/BasktLogo.png" alt="" />
          </span>
          <span>
            <strong>Baskt</strong>
            <small>Modern portfolio automation</small>
          </span>
        </div>
        <h1>Build, test, and fund portfolios that meet your needs.</h1>
        <p>
          A professional workspace for creating weighted stock baskets, monitoring
          equity, and managing account transfers.
        </p>
      </section>

      <section className="auth-card">
        <h2>{challenge ? "Set a new password" : "Sign in to Baskt"}</h2>
        <ErrorBanner message={error} />
        <SuccessBanner message={success} />

        {challenge ? (
          <form onSubmit={submitNewPassword} className="form-stack">
            <label>
              New password
              <input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                autoComplete="new-password"
                required
              />
            </label>
            <button className="primary-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Saving..." : "Continue"}
            </button>
          </form>
        ) : (
          <form onSubmit={submitLogin} className="form-stack">
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <button className="primary-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Signing in..." : "Sign in"}
            </button>
          </form>
        )}

        <div className="auth-links">
          <button type="button" onClick={onShowSignup}>
            Create an account
          </button>
          <a href={forgotPasswordUrl}>Forgot password?</a>
        </div>
      </section>
    </main>
  );
}
