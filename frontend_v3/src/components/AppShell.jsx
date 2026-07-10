const navItems = [
  { id: "home", label: "Home", icon: "H" },
  { id: "make", label: "Make a Baskt", icon: "+" },
  { id: "my-baskts", label: "My Baskts", icon: "B" },
  { id: "explore", label: "Explore Baskts & Stocks", icon: "E" },
  { id: "transfer", label: "Transfer", icon: "$" },
];

export default function AppShell({ currentPage, onNavigate, onLogout, children }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="brand-lockup" type="button" onClick={() => onNavigate("home")}>
          <span className="brand-mark">
            <img src="/BasktLogo.png" alt="" />
          </span>
          <span>
            <strong>Baskt</strong>
          </span>
        </button>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={currentPage === item.id ? "nav-item active" : "nav-item"}
              type="button"
              onClick={() => onNavigate(item.id)}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="mini-panel">
            <span className="mini-dot" />
            <p>Live brokerage data</p>
          </div>
          <button className="ghost-button full-width" type="button" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="main-stack">
        <header className="topbar">
          <div>
            <h1>{navItems.find((item) => item.id === currentPage)?.label || "Baskt"}</h1>
          </div>
        </header>
        <main className="content-area">{children}</main>
      </div>
    </div>
  );
}
