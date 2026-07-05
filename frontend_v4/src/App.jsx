import { useEffect, useMemo, useState } from "react";
import AppShell from "./components/AppShell";
import BasktPage from "./pages/BasktPage";
import ExplorePage from "./pages/ExplorePage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import MakeABaskt from "./pages/MakeABaskt";
import MyBaskts from "./pages/MyBaskts";
import SignupPage from "./pages/SignupPage";
import SettingsPage from "./pages/SettingsPage";
import StockPage from "./pages/StockPage";
import Transfer from "./pages/Transfer";
import { cognitoConfig } from "./authConfig";
import { clearSession, getIdToken } from "./lib/session";

const STATIC_PAGES = new Set([
  "home",
  "make",
  "my-baskts",
  "explore",
  "transfer",
  "settings",
]);

function decodeRouteId(value) {
  try {
    return decodeURIComponent(value || "");
  } catch {
    return "";
  }
}

function readLocation() {
  const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [section, encodedId] = parts;
  const id = decodeRouteId(encodedId);

  if (section === "baskts" && id) {
    return { route: { page: "baskt-detail", id }, authView: "login" };
  }
  if (section === "stocks" && id) {
    return { route: { page: "stock-detail", id }, authView: "login" };
  }
  if (section === "make" && id) {
    return { route: { page: "make", id }, authView: "login" };
  }
  if (section === "signup") {
    return { route: { page: "home" }, authView: "signup" };
  }
  if (section === "login") {
    return { route: { page: "home" }, authView: "login" };
  }
  if (STATIC_PAGES.has(section)) {
    return { route: { page: section }, authView: "login" };
  }
  return { route: { page: "home" }, authView: "login" };
}

function routeHash(route) {
  if (route.page === "baskt-detail") {
    return `#/baskts/${encodeURIComponent(route.id)}`;
  }
  if (route.page === "stock-detail") {
    return `#/stocks/${encodeURIComponent(route.id)}`;
  }
  if (route.page === "make" && route.id) {
    return `#/make/${encodeURIComponent(route.id)}`;
  }
  return `#/${route.page}`;
}

export default function App() {
  const initialLocation = useMemo(readLocation, []);
  const [isAuthenticated, setIsAuthenticated] = useState(Boolean(getIdToken()));
  const [authView, setAuthView] = useState(initialLocation.authView);
  const [route, setRoute] = useState(initialLocation.route);
  const [basktDetailBackPage, setBasktDetailBackPage] = useState("my-baskts");
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

  useEffect(() => {
    function syncFromLocation() {
      const location = readLocation();
      setRoute(location.route);
      setAuthView(location.authView);
    }

    window.addEventListener("hashchange", syncFromLocation);
    if (!window.location.hash) {
      window.history.replaceState(null, "", isAuthenticated ? "#/home" : "#/login");
    }
    return () => window.removeEventListener("hashchange", syncFromLocation);
  }, [isAuthenticated]);

  function navigate(nextRoute, { replace = false } = {}) {
    setRoute(nextRoute);
    const nextHash = routeHash(nextRoute);
    if (replace) {
      window.history.replaceState(null, "", nextHash);
    } else if (window.location.hash !== nextHash) {
      window.location.hash = nextHash;
    }
  }

  function showAuthView(view) {
    setAuthView(view);
    window.history.replaceState(null, "", view === "signup" ? "#/signup" : "#/login");
  }

  function logout() {
    clearSession();
    setIsAuthenticated(false);
    setAuthView("login");
    setRoute({ page: "home" });
    window.history.replaceState(null, "", "#/login");
  }

  if (!isAuthenticated) {
    return authView === "signup" ? (
      <SignupPage onBackToLogin={() => showAuthView("login")} />
    ) : (
      <LoginPage
        forgotPasswordUrl={forgotPasswordUrl}
        onAuthenticated={() => {
          setIsAuthenticated(true);
          navigate({ page: "home" }, { replace: true });
        }}
        onShowSignup={() => showAuthView("signup")}
      />
    );
  }

  const currentPage = route.page;
  let page = (
    <HomePage
      onOpenInvestment={(investment) => {
        if (investment.type === "Stock") {
          setStockDetailBackPage("home");
          navigate({ page: "stock-detail", id: investment.portfolioId });
          return;
        }

        setBasktDetailBackPage("home");
        navigate({ page: "baskt-detail", id: investment.portfolioId });
      }}
    />
  );

  if (currentPage === "make") {
    page = (
      <MakeABaskt
        editingPortfolioId={route.id || null}
        onSaved={() => navigate({ page: "my-baskts" })}
      />
    );
  } else if (currentPage === "my-baskts") {
    page = (
      <MyBaskts
        onCreateBaskt={() => navigate({ page: "make" })}
        onOpenBaskt={(portfolioId) => {
          setBasktDetailBackPage("my-baskts");
          navigate({ page: "baskt-detail", id: portfolioId });
        }}
      />
    );
  } else if (currentPage === "baskt-detail" && route.id) {
    page = (
      <BasktPage
        portfolioId={route.id}
        onBack={() => navigate({ page: basktDetailBackPage })}
        onUpdate={() => navigate({ page: "make", id: route.id })}
      />
    );
  } else if (currentPage === "transfer") {
    page = <Transfer />;
  } else if (currentPage === "stock-detail" && route.id) {
    page = (
      <StockPage
        stockId={route.id}
        onBack={() => navigate({ page: stockDetailBackPage })}
      />
    );
  } else if (currentPage === "explore") {
    page = (
      <ExplorePage
        onOpenBaskt={(portfolioId) => {
          setBasktDetailBackPage("explore");
          navigate({ page: "baskt-detail", id: portfolioId });
        }}
        onOpenStock={(stock) => {
          setStockDetailBackPage("explore");
          navigate({ page: "stock-detail", id: stock.stock_id });
        }}
      />
    );
  } else if (currentPage === "settings") {
    page = <SettingsPage />;
  }

  return (
    <AppShell
      currentPage={currentPage}
      onNavigate={(pageName) => navigate({ page: pageName })}
      onLogout={logout}
      onOpenBaskt={(portfolioId) => {
        setBasktDetailBackPage(
          currentPage === "baskt-detail" || currentPage === "stock-detail" ? "explore" : currentPage
        );
        navigate({ page: "baskt-detail", id: portfolioId });
      }}
      onOpenStock={(stockId) => {
        setStockDetailBackPage(
          currentPage === "baskt-detail" || currentPage === "stock-detail" ? "explore" : currentPage
        );
        navigate({ page: "stock-detail", id: stockId });
      }}
    >
      {page}
    </AppShell>
  );
}
