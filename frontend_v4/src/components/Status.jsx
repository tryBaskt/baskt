import { useEffect, useState } from "react";

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
  return <Toast message={message} tone="error" />;
}

export function SuccessBanner({ message }) {
  return <Toast message={message} tone="success" />;
}

function Toast({ message, tone }) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (!message) {
      setIsVisible(false);
      return undefined;
    }

    setIsVisible(true);
    const timeoutId = window.setTimeout(() => {
      setIsVisible(false);
    }, 5000);

    return () => window.clearTimeout(timeoutId);
  }, [message]);

  if (!message || !isVisible) {
    return null;
  }

  return (
    <div className={`toast toast-${tone}`} role={tone === "error" ? "alert" : "status"} aria-live="polite">
      {tone === "error" ? "Error" : message}
    </div>
  );
}
