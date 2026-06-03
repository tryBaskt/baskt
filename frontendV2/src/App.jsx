import { useEffect, useState } from "react";
import { cognitoConfig } from "./authConfig";
import { signUp, confirmSignUp, signIn, completeNewPassword } from "./cognitoAuth";
import LoginPage from "./Pages/LoginPage";
import AgreementPage from "./Pages/SignUpPages/AgreementPage";
import ContactPage from "./Pages/SignUpPages/ContactPage";
import DisclosurePage from "./Pages/SignUpPages/DisclosurePage";
import IdentityPage from "./Pages/SignUpPages/IdentityPage";
import NewPasswordPage from "./Pages/SignUpPages/NewPasswordPage";
import HomePage from "./Pages/HomePage";
import MakeBasktPage from "./Pages/MakeBasktPage";
import MyBasktsPage from "./Pages/MyBasktsPage";
import BasktPage from "./Pages/BasktPage";
import AuthenticatedLayout from "./layouts/AuthenticatedLayout";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const SIGNUP_DRAFT_STORAGE_KEY = "basktSignupDraft";

function readSignupDraft() {
  try {
    return JSON.parse(sessionStorage.getItem(SIGNUP_DRAFT_STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function writeSignupDraft(updates) {
  const nextDraft = {
    ...readSignupDraft(),
    ...updates,
  };
  sessionStorage.setItem(SIGNUP_DRAFT_STORAGE_KEY, JSON.stringify(nextDraft));
  return nextDraft;
}

function clearSignupDraft() {
  sessionStorage.removeItem(SIGNUP_DRAFT_STORAGE_KEY);
}

export default function App() {
  const initialSignupDraft = readSignupDraft();
  const [view, setView] = useState("login");
  const [email, setEmail] = useState(() => localStorage.getItem("lastLoginEmail") || "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPassword, setConfirmNewPassword] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");
  const [newPasswordChallenge, setNewPasswordChallenge] = useState(null);
  const [signupStep, setSignupStep] = useState(initialSignupDraft.signupStep || "contact");
  const [signupContact, setSignupContact] = useState(initialSignupDraft.contact || null);
  const [signupIdentity, setSignupIdentity] = useState(initialSignupDraft.identity || null);
  const [signupDisclosure, setSignupDisclosure] = useState(initialSignupDraft.disclosures || null);
  const [signupAgreements, setSignupAgreements] = useState(initialSignupDraft.agreements || null);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const [currentPage, setCurrentPage] = useState("home");
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
      if (error?.name === "NewPasswordRequired") {
        setNewPasswordChallenge({
          cognitoUser: error.cognitoUser,
          userAttributes: error.userAttributes || {},
        });
        setNewPassword("");
        setConfirmNewPassword("");
        setPassword("");
        setView("new-password");
        return;
      }

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
    setView("login");
    setErrorMessage("");
    setStatusMessage("");
    setPassword("");
    setNewPassword("");
    setConfirmNewPassword("");
    setNewPasswordChallenge(null);
  }

  function onSignupContactSubmit(contactData) {
    setErrorMessage("");
    setStatusMessage("");
    writeSignupDraft({ contact: contactData, signupStep: "identity" });
    setSignupContact(contactData);
    setEmail(contactData.email_address);
    setSignupStep("identity");
  }

  function onSignupIdentitySubmit(identityData) {
    setErrorMessage("");
    setStatusMessage("");
    writeSignupDraft({ identity: identityData, signupStep: "disclosure" });
    setSignupIdentity(identityData);
    setSignupStep("disclosure");
  }

  function onSignupDisclosureSubmit(disclosureData) {
    setErrorMessage("");
    setStatusMessage("");
    writeSignupDraft({ disclosures: disclosureData, signupStep: "agreement" });
    setSignupDisclosure(disclosureData);
    setSignupStep("agreement");
  }

  function onBackToLoginFromSignup() {
    setErrorMessage("");
    setStatusMessage("");
    setView("login");
  }

  async function onNewPasswordSubmit() {
    if (!newPasswordChallenge?.cognitoUser) {
      setErrorMessage("Please log in again before setting a new password.");
      setView("login");
      return;
    }

    setErrorMessage("");
    setStatusMessage("");

    try {
      setIsSubmitting(true);
      const tokens = await completeNewPassword(
        newPasswordChallenge.cognitoUser,
        newPassword,
        newPasswordChallenge.userAttributes
      );
      sessionStorage.setItem("idToken", tokens.idToken);
      sessionStorage.setItem("accessToken", tokens.accessToken || "");
      sessionStorage.setItem("refreshToken", tokens.refreshToken || "");
      localStorage.setItem("lastLoginEmail", email.trim());
      setIsAuthenticated(true);
      setNewPassword("");
      setConfirmNewPassword("");
      setNewPasswordChallenge(null);
    } catch (error) {
      setErrorMessage(error?.message || "Failed to set new password.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function onSignupAgreementSubmit({ agreements, password: signupPassword }) {
    setErrorMessage("");
    setStatusMessage("");
    writeSignupDraft({ agreements, signupStep: "agreement" });
    setSignupAgreements(agreements);

    if (!signupContact || !signupIdentity || !signupDisclosure) {
      setErrorMessage("Please complete every signup step before submitting.");
      return;
    }

    try {
      setIsSubmitting(true);
      const payload = {
        contact: signupContact,
        identity: signupIdentity,
        disclosures: signupDisclosure,
        agreements,
        password: signupPassword,
      };

      const response = await fetch(`${API_BASE_URL}/accounts/create-baskt-account`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        throw new Error(errorPayload?.detail || "Failed to create account.");
      }

      clearSignupDraft();
      setStatusMessage("Account submitted successfully. You can now sign in.");
      setView("login");
      setSignupStep("contact");
      setSignupContact(null);
      setSignupIdentity(null);
      setSignupDisclosure(null);
      setSignupAgreements(null);
      setPassword("");
      setConfirmPassword("");
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
      setSignupStep("contact");
      setSignupContact(null);
      setSignupIdentity(null);
      setSignupDisclosure(null);
      setSignupAgreements(null);
      clearSignupDraft();
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
            setPassword("");
            setConfirmPassword("");
            setSignupStep("contact");
            writeSignupDraft({ signupStep: "contact" });
            setView("signup");
          }}
          isSubmitting={isSubmitting}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}

      {view === "new-password" ? (
        <NewPasswordPage
          email={email}
          newPassword={newPassword}
          confirmNewPassword={confirmNewPassword}
          setNewPassword={setNewPassword}
          setConfirmNewPassword={setConfirmNewPassword}
          onNewPasswordSubmit={onNewPasswordSubmit}
          onBackToLogin={() => {
            setErrorMessage("");
            setStatusMessage("");
            setNewPassword("");
            setConfirmNewPassword("");
            setNewPasswordChallenge(null);
            setView("login");
          }}
          isSubmitting={isSubmitting}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}

      {view === "signup" && signupStep === "contact" ? (
        <ContactPage
          initialContact={signupContact}
          onContactSubmit={onSignupContactSubmit}
          onBackToLogin={onBackToLoginFromSignup}
          forgotPasswordUrl={forgotPasswordUrl}
          isSubmitting={isSubmitting}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}

      {view === "signup" && signupStep === "identity" ? (
        <IdentityPage
          contactCountry={signupContact?.country}
          initialIdentity={signupIdentity}
          onIdentitySubmit={onSignupIdentitySubmit}
          onBackToLogin={onBackToLoginFromSignup}
          onBackToContact={() => {
            setErrorMessage("");
            setStatusMessage("");
            writeSignupDraft({ signupStep: "contact" });
            setSignupStep("contact");
          }}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}

      {view === "signup" && signupStep === "disclosure" ? (
        <DisclosurePage
          initialDisclosure={signupDisclosure}
          onDisclosureSubmit={onSignupDisclosureSubmit}
          onBackToLogin={onBackToLoginFromSignup}
          onBackToIdentity={() => {
            setErrorMessage("");
            setStatusMessage("");
            writeSignupDraft({ signupStep: "identity" });
            setSignupStep("identity");
          }}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}

      {view === "signup" && signupStep === "agreement" ? (
        <AgreementPage
          initialAgreements={signupAgreements}
          password={password}
          confirmPassword={confirmPassword}
          setPassword={setPassword}
          setConfirmPassword={setConfirmPassword}
          onAgreementSubmit={onSignupAgreementSubmit}
          isSubmitting={isSubmitting}
          onBackToLogin={onBackToLoginFromSignup}
          onBackToDisclosure={() => {
            setErrorMessage("");
            setStatusMessage("");
            writeSignupDraft({ signupStep: "disclosure" });
            setSignupStep("disclosure");
          }}
          statusMessage={statusMessage}
          errorMessage={errorMessage}
        />
      ) : null}
    </main>
  );
}
