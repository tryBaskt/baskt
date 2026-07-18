import { getIdToken } from "./session";
import { requiredEnv } from "../config/env";

export const API_BASE_URL = requiredEnv("VITE_API_BASE_URL").replace(/\/$/, "");

function formatErrorPayload(payload, fallback) {
  if (!payload) {
    return fallback;
  }

  if (typeof payload.detail === "string") {
    return payload.detail;
  }

  if (payload.detail?.message) {
    return payload.detail.message;
  }

  if (payload.message) {
    return payload.message;
  }

  return fallback;
}

export async function apiRequest(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getIdToken();

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (API_BASE_URL.includes("ngrok-free.dev")) {
    headers.set("ngrok-skip-browser-warning", "true");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(formatErrorPayload(payload, `Request failed with status ${response.status}.`));
  }

  if (response.status === 204) {
    return null;
  }

  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

export function toQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  });
  const value = query.toString();
  return value ? `?${value}` : "";
}
