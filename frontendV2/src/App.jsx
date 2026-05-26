import { useEffect, useState } from "react";
import { cognitoConfig } from "./authConfig";
import { signUp, confirmSignUp, signIn } from "./cognitoAuth";
import LoginPage from "./Pages/LoginPage";
import SignUpPage from "./Pages/SignUpPage";
import HomePage from "./Pages/HomePage";
import MakeBasktPage from "./Pages/MakeBasktPage";
import MyBasktsPage from "./Pages/MyBasktsPage";
import BasktPage from "./Pages/BasktPage";
import AuthenticatedLayout from "./layouts/AuthenticatedLayout";

export default function App() {
  const [view, setView] = useState("login");
  const [email, setEmail] = useState(() => localStorage.getItem("lastLoginEmail") || "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [currentPage, setCurrentPage] = useState("make-baskt");
  const [selectedBaskt, setSelectedBaskt] = useState(null);

  useEffect(() => {
    const storedIdToken = sessionStorage.getItem("idToken");

    if (storedIdToken) {
      setIsAuthenticated(true);
    }

    setIsAuthChecking(false);
  }, []);

  async function onSubmit(event) {
    event.preventDefault();
    setErrorMessage("");
    setStatusMessage("");

    try {
      setIsSubmitting(true);
      const tokens = await signIn(email.trim(), password);
      sessionStorage.setItem("idToken", tokens.idToken);
      sessionStorage.setItem("accessToken", tokens.accessToken || "");
      sessionStorage.setItem("refreshToken", tokens.refreshToken || "");
      localStorage.setItem("lastLoginEmail", email.trim());
      setIsAuthenticated(true);
      setPassword("");
    } catch (error) {
      setErrorMessage(error?.message || "Sign in failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function onLogout() {
    if (email.trim()) {
      localStorage.setItem("lastLoginEmail", email.trim());
    }
    sessionStorage.removeItem("idToken");
    sessionStorage.removeItem("accessToken");
    sessionStorage.removeItem("refreshToken");
    setIsAuthenticated(false);
    setSelectedBaskt(null);
  }

  async function onSignUpSubmit(event) {
    event.preventDefault();
    setErrorMessage("");
    setStatusMessage("");

    if (password !== confirmPassword) {
      setErrorMessage("Passwords do not match.");
      return;
    }

    try {
      setIsSubmitting(true);
      await signUp(email.trim(), password);
      setPendingEmail(email.trim());
      setView("signup-confirm");
      setStatusMessage("Account created. Enter the verification code sent to your email.");
    } catch (error) {
      setErrorMessage(error?.message || "Failed to create account.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function onConfirmSubmit(event) {
    event.preventDefault();
    setErrorMessage("");
    setStatusMessage("");

    try {
      setIsSubmitting(true);
      await confirmSignUp(pendingEmail.trim(), verificationCode.trim());
      setStatusMessage("Account verified. You can now sign in.");
      setView("login");
      setPassword("");
      setConfirmPassword("");
      setVerificationCode("");
    } catch (error) {
      setErrorMessage(error?.message || "Failed to verify account.");
    } finally {
      setIsSubmitting(false);
    }
  }

  const { domain, userPoolWebClientId, redirectSignIn } = cognitoConfig;
  const commonAuthQuery =
    `client_id=${encodeURIComponent(userPoolWebClientId)}&` +
    `redirect_uri=${encodeURIComponent(redirectSignIn)}&` +
    `response_type=code&` +
    `scope=${encodeURIComponent("openid email profile")}`;
  const forgotPasswordUrl = `https://${domain}/forgotPassword?${commonAuthQuery}`;

  if (isAuthChecking) {
    return (
      <main className="page-shell">
        <div className="ambient-grid" aria-hidden="true" />
        <section className="login-card" aria-live="polite">
          <p className="eyebrow">Baskt</p>
          <h1>Signing you in...</h1>
          <p className="subtitle">Completing secure login with Cognito.</p>
        </section>
      </main>
    );
  }

  if (isAuthenticated) {
    let pageContent = <MakeBasktPage />;
    if (currentPage === "home") {
      pageContent = <HomePage />;
    } else if (currentPage === "my-baskts") {
      pageContent = (
        <MyBasktsPage
          onOpenBaskt={(baskt) => {
            setSelectedBaskt(baskt);
            setCurrentPage("baskt-detail");
          }}
        />
      );
    } else if (currentPage === "baskt-detail") {
      pageContent = (
        <BasktPage
          selectedBaskt={selectedBaskt}
          onBack={() => setCurrentPage("my-baskts")}
        />
      );
    }

    return (
      <AuthenticatedLayout onLogout={onLogout} currentPage={currentPage} onSelectPage={setCurrentPage}>
        {pageContent}
      </AuthenticatedLayout>
    );
  }

  const isSignUpView = view === "signup" || view === "signup-confirm";

  return (
    <main className="page-shell">
      <div className="ambient-grid" aria-hidden="true" />
      {view === "login" ? (
        <LoginPage
          email={email}
          password={password}
          setEmail={setEmail}
          setPassword={setPassword}
          onSubmit={onSubmit}
          forgotPasswordUrl={forgotPasswordUrl}
          onShowSignUp={() => {
            setErrorMessage("");
            setStatusMessage("");
            setView("signup");
          }}
          isSubmitting={isSubmitting}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}

      {isSignUpView ? (
        <SignUpPage
          isConfirmStep={view === "signup-confirm"}
          email={email}
          password={password}
          confirmPassword={confirmPassword}
          verificationCode={verificationCode}
          pendingEmail={pendingEmail}
          setEmail={setEmail}
          setPassword={setPassword}
          setConfirmPassword={setConfirmPassword}
          setVerificationCode={setVerificationCode}
          setPendingEmail={setPendingEmail}
          onSignUpSubmit={onSignUpSubmit}
          onConfirmSubmit={onConfirmSubmit}
          onBackToLogin={() => {
            setErrorMessage("");
            setStatusMessage("");
            setView("login");
          }}
          forgotPasswordUrl={forgotPasswordUrl}
          isSubmitting={isSubmitting}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}
    </main>
  );
}