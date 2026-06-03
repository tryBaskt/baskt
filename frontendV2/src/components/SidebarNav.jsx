export default function SidebarNav({ onLogout, currentPage, onSelectPage }) {
  const isHomeActive = currentPage === "home";
  const isMakeBasktActive = currentPage === "make-baskt";
  const isMyBasktsActive = currentPage === "my-baskts";

  return (
    <aside className="home-sidebar" aria-label="Primary navigation">
      <div className="home-brand">Baskt</div>
      <nav className="home-nav">
        <button
          type="button"
          className={`home-nav-button${isHomeActive ? " is-active" : ""}`}
          aria-current={isHomeActive ? "page" : undefined}
          onClick={() => onSelectPage("home")}
        >
          <span className="home-nav-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="M4 19h16v1.5H4V19zm1-2.5l4.2-4.7 3.2 2.8 5.2-6.8 1.4 1.1-6.5 8.4-3.1-2.7-3.2 3.6L5 16.5z" />
            </svg>
          </span>
          <span>Home</span>
        </button>

        <button
          type="button"
          className={`home-nav-button${isMakeBasktActive ? " is-active" : ""}`}
          aria-current={isMakeBasktActive ? "page" : undefined}
          onClick={() => onSelectPage("make-baskt")}
        >
          <span className="home-nav-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="M12 3l2.45 4.96L20 8.78l-4 3.9.94 5.52L12 15.62 7.06 18.2 8 12.68 4 8.78l5.55-.82L12 3z" />
            </svg>
          </span>
          <span>Make a Baskt</span>
        </button>

        <button
          type="button"
          className={`home-nav-button${isMyBasktsActive ? " is-active" : ""}`}
          aria-current={isMyBasktsActive ? "page" : undefined}
          onClick={() => onSelectPage("my-baskts")}
        >
          <span className="home-nav-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" focusable="false">
              <path d="M4 5.75A1.75 1.75 0 015.75 4h12.5A1.75 1.75 0 0120 5.75v12.5A1.75 1.75 0 0118.25 20H5.75A1.75 1.75 0 014 18.25V5.75zm2.5.25v3h11V6h-11zm0 5v7h4v-7h-4zm6 0v7h5v-7h-5z" />
            </svg>
          </span>
          <span>My Baskts</span>
        </button>
      </nav>
      <button type="button" className="home-logout" onClick={onLogout}>
        Sign out
      </button>
    </aside>
  );
}
