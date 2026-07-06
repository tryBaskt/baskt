export function currency(value, fallback = "$0.00") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(numeric);
}

export function percent(value, digits = 2) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "0.00%";
  }

  const formatted = Math.abs(numeric) >= 1_000_000
    ? numeric.toExponential(digits)
    : numeric.toFixed(digits);

  return `${formatted}%`;
}

export function formatMetricNumber(
  value,
  { digits = 2, fallback = "Not available", suffix = "" } = {}
) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }

  const magnitude = Math.abs(numeric);
  const formatted = magnitude !== 0 && (magnitude < 0.01 || magnitude >= 1_000_000)
    ? numeric.toExponential(digits)
    : numeric.toFixed(digits);

  return `${formatted}${suffix}`;
}

export function formatDate(value) {
  if (!value) {
    return "Not available";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

export function formatDateTime(value) {
  if (!value) {
    return "Not available";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
