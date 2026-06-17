export function LoadingState({ title = "Loading", message = "Fetching the latest data." }) {
  return (
    <div className="state-panel" aria-live="polite">
      <span className="loader" />
      <h2>{title}</h2>
      <p>{message}</p>
    </div>
  );
}

export function EmptyState({ title, message, action }) {
  return (
    <div className="state-panel">
      <h2>{title}</h2>
      <p>{message}</p>
      {action}
    </div>
  );
}

export function ErrorBanner({ message }) {
  if (!message) {
    return null;
  }

  return <div className="alert alert-error">{message}</div>;
}

export function SuccessBanner({ message }) {
  if (!message) {
    return null;
  }

  return <div className="alert alert-success">{message}</div>;
}
