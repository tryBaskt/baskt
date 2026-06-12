import { useMemo, useState } from "react";
import AppShell from "./components/AppShell";
import BasktPage from "./pages/BasktPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MakeABaskt from "./pages/MakeABaskt";
import MyBaskts from "./pages/MyBaskts";
import SignupPage from "./pages/SignupPage";
import Transfer from "./pages/Transfer";
import { cognitoConfig } from "./authConfig";
import { clearSession, getIdToken } from "./lib/session";

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(getIdToken()));
  const [authView, setAuthView] = useState("login");
  const [currentPage, setCurrentPage] = useState("home");
  const [selectedPortfolioId, setSelectedPortfolioId] = useState(null);
  const [editingBaskt, setEditingBaskt] = useState(null);

  const forgotPasswordUrl = useMemo(() => {
    const query = new URLSearchParams({
      client_id: cognitoConfig.userPoolWebClientId,
      redirect_uri: cognitoConfig.redirectSignIn,
      response_type: "code",
      scope: "openid email profile",
    });
    return `https://${cognitoConfig.domain}/forgotPassword?${query.toString()}`;
  }, []);

  function navigate(page) {
    if (page !== "make") {
      setEditingBaskt(null);
    }
    setCurrentPage(page);
  }

  function logout() {
    clearSession();
    setIsAuthenticated(false);
    setCurrentPage("home");
    setSelectedPortfolioId(null);
    setEditingBaskt(null);
  }

  if (!isAuthenticated) {
    return authView === "signup" ? (
      <SignupPage onBackToLogin={() => setAuthView("login")} />
    ) : (
      <LoginPage
        forgotPasswordUrl={forgotPasswordUrl}
        onAuthenticated={() => setIsAuthenticated(true)}
        onShowSignup={() => setAuthView("signup")}
      />
    );
  }

  let page = <HomePage />;
  if (currentPage === "make") {
    page = <MakeABaskt editingBaskt={editingBaskt} onSaved={() => setCurrentPage("my-baskts")} />;
  } else if (currentPage === "my-baskts") {
    page = (
      <MyBaskts
        onCreateBaskt={() => navigate("make")}
        onOpenBaskt={(portfolioId) => {
          setSelectedPortfolioId(portfolioId);
          setCurrentPage("baskt-detail");
        }}
      />
    );
  } else if (currentPage === "baskt-detail") {
    page = (
      <BasktPage
        portfolioId={selectedPortfolioId}
        onBack={() => setCurrentPage("my-baskts")}
        onUpdate={(baskt) => {
          setEditingBaskt(baskt);
          setCurrentPage("make");
        }}
      />
    );
  } else if (currentPage === "transfer") {
    page = <Transfer />;
  }

  return (
    <AppShell currentPage={currentPage} onNavigate={navigate} onLogout={logout}>
      {page}
    </AppShell>
  );
}
