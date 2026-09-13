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

export function ValidationModal({ message, onClose }) {
  if (!message) {
    return null;
  }

  return (
    <div className="validation-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="validation-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="validation-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="validation-modal-header">
          <h2 id="validation-modal-title">Trade needs a quick fix</h2>
          <p>{message}</p>
        </div>
        <div className="validation-modal-actions">
          <button className="primary-button" type="button" onClick={onClose}>
            Go back
          </button>
        </div>
      </div>
    </div>
  );
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
      {message}
    </div>
  );
}
