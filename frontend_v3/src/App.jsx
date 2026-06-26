import { useMemo, useState } from "react";
import AppShell from "./components/AppShell";
import BasktPage from "./pages/BasktPage";
import ExplorePage from "./pages/ExplorePage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MakeABaskt from "./pages/MakeABaskt";
import MyBaskts from "./pages/MyBaskts";
import SignupPage from "./pages/SignupPage";
import StockPage from "./pages/StockPage";
import Transfer from "./pages/Transfer";
import { cognitoConfig } from "./authConfig";
import { clearSession, getIdToken } from "./lib/session";

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(getIdToken()));
  const [authView, setAuthView] = useState("login");
  const [currentPage, setCurrentPage] = useState("home");
  const [selectedPortfolioId, setSelectedPortfolioId] = useState(null);
  const [basktDetailBackPage, setBasktDetailBackPage] = useState("my-baskts");
  const [editingBaskt, setEditingBaskt] = useState(null);
  const [selectedStockRef, setSelectedStockRef] = useState(null);
  const [stockDetailBackPage, setStockDetailBackPage] = useState("explore");

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
    setSelectedStockRef(null);
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

  let page = (
    <HomePage
      onOpenInvestment={(investment) => {
        if (investment.type === "Stock") {
          setSelectedStockRef({
            stockId: investment.portfolioId,
            symbol: investment.name,
          });
          setStockDetailBackPage("home");
          setCurrentPage("stock-detail");
          return;
        }

        setSelectedPortfolioId(investment.portfolioId);
        setBasktDetailBackPage("home");
        setCurrentPage("baskt-detail");
      }}
    />
  );
  if (currentPage === "make") {
    page = <MakeABaskt editingBaskt={editingBaskt} onSaved={() => setCurrentPage("my-baskts")} />;
  } else if (currentPage === "my-baskts") {
    page = (
      <MyBaskts
        onCreateBaskt={() => navigate("make")}
        onOpenBaskt={(portfolioId) => {
          setSelectedPortfolioId(portfolioId);
          setBasktDetailBackPage("my-baskts");
          setCurrentPage("baskt-detail");
        }}
      />
    );
  } else if (currentPage === "baskt-detail") {
    page = (
      <BasktPage
        portfolioId={selectedPortfolioId}
        onBack={() => setCurrentPage(basktDetailBackPage)}
        onUpdate={(baskt) => {
          setEditingBaskt(baskt);
          setCurrentPage("make");
        }}
      />
    );
  } else if (currentPage === "transfer") {
    page = <Transfer />;
  } else if (currentPage === "stock-detail" && selectedStockRef) {
    page = (
      <StockPage
        stockId={selectedStockRef.stockId}
        symbol={selectedStockRef.symbol}
        onBack={() => setCurrentPage(stockDetailBackPage)}
      />
    );
  } else if (currentPage === "explore") {
    page = (
      <ExplorePage
        onOpenBaskt={(portfolioId) => {
          setSelectedPortfolioId(portfolioId);
          setBasktDetailBackPage("explore");
          setCurrentPage("baskt-detail");
        }}
        onOpenStock={(stock) => {
          setSelectedStockRef({
            stockId: stock.stock_id,
            symbol: stock.symbol,
          });
          setStockDetailBackPage("explore");
          setCurrentPage("stock-detail");
        }}
      />
    );
  }

  return (
    <AppShell currentPage={currentPage} onNavigate={navigate} onLogout={logout}>
      {page}
    </AppShell>
  );
}
