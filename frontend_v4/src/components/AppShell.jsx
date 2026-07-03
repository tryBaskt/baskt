import GlobalSearch from "./GlobalSearch";

const navItems = [
  { id: "home", label: "Portfolio" },
  { id: "make", label: "Create" },
  { id: "my-baskts", label: "My Baskts" },
  { id: "explore", label: "Explore" },
  { id: "transfer", label: "Transfers" },
];

export default function AppShell({ currentPage, onNavigate, onLogout, onOpenBaskt, onOpenStock, children }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand-lockup" type="button" onClick={() => onNavigate("home")} aria-label="Baskt home">
          <span className="brand-mark"><img src="/BasktLogo.png" alt="" /></span>
          <strong>BASKT</strong>
        </button>

        <GlobalSearch onOpenBaskt={onOpenBaskt} onOpenStock={onOpenStock} />

        <nav className="top-nav" aria-label="Primary navigation">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={currentPage === item.id ? "nav-item active" : "nav-item"}
              type="button"
              onClick={() => onNavigate(item.id)}
            >
              {item.label}
            </button>
          ))}
          <button className="account-button" type="button" onClick={onLogout}>Sign out</button>
        </nav>
      </header>
      <main className="content-area">{children}</main>
    </div>
  );
}
