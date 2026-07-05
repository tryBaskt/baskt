import { useEffect, useRef, useState } from "react";
import GlobalSearch from "./GlobalSearch";

const navItems = [
  { id: "home", label: "Portfolio" },
  { id: "make", label: "Create" },
  { id: "my-baskts", label: "My Baskts" },
  { id: "explore", label: "Explore" },
  { id: "transfer", label: "Transfers" },
];

export default function AppShell({ currentPage, onNavigate, onLogout, onOpenBaskt, onOpenStock, children }) {
  const [isAccountMenuOpen, setIsAccountMenuOpen] = useState(false);
  const accountMenuRef = useRef(null);

  useEffect(() => {
    if (!isAccountMenuOpen) return undefined;

    function closeAccountMenu(event) {
      if (event.key === "Escape") {
        setIsAccountMenuOpen(false);
        return;
      }
      if (
        event.type === "pointerdown"
        && !accountMenuRef.current?.contains(event.target)
      ) {
        setIsAccountMenuOpen(false);
      }
    }

    document.addEventListener("pointerdown", closeAccountMenu);
    document.addEventListener("keydown", closeAccountMenu);
    return () => {
      document.removeEventListener("pointerdown", closeAccountMenu);
      document.removeEventListener("keydown", closeAccountMenu);
    };
  }, [isAccountMenuOpen]);

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
          <div className="account-menu" ref={accountMenuRef}>
            <button
              className={currentPage === "settings" ? "account-button active" : "account-button"}
              type="button"
              aria-haspopup="menu"
              aria-expanded={isAccountMenuOpen}
              onClick={() => setIsAccountMenuOpen((isOpen) => !isOpen)}
            >
              Account
              <span className="account-menu-chevron" aria-hidden="true">⌄</span>
            </button>
            {isAccountMenuOpen && (
              <div className="account-menu-dropdown" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setIsAccountMenuOpen(false);
                    onNavigate("settings");
                  }}
                >
                  Settings
                </button>
                <button
                  className="account-menu-signout"
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setIsAccountMenuOpen(false);
                    onLogout();
                  }}
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </nav>
      </header>
      <main className="content-area">{children}</main>
    </div>
  );
}
