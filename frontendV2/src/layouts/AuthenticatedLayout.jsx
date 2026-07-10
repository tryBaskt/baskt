import SidebarNav from "../components/SidebarNav";

export default function AuthenticatedLayout({ onLogout, currentPage, onSelectPage, children }) {
  return (
    <main className="home-shell">
      <div className="home-layout">
        <SidebarNav onLogout={onLogout} currentPage={currentPage} onSelectPage={onSelectPage} />
        <section className="home-content">{children}</section>
      </div>
    </main>
  );
}
