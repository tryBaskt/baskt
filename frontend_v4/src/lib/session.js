const TOKEN_KEY = "baskt.v3.idToken";
const ACCESS_TOKEN_KEY = "baskt.v3.accessToken";
const REFRESH_TOKEN_KEY = "baskt.v3.refreshToken";

export function saveSession(tokens) {
  sessionStorage.setItem(TOKEN_KEY, tokens.idToken || "");
  sessionStorage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken || "");
  sessionStorage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken || "");
}

export function clearSession() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function getIdToken() {
  return sessionStorage.getItem(TOKEN_KEY) || sessionStorage.getItem("idToken") || "";
}

export function decodeJwt(token) {
  if (!token) {
    return null;
  }

  try {
    const payload = token.split(".")[1];
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(globalThis.atob(normalized));
  } catch {
    return null;
  }
}

export function getCurrentUserClaims() {
  return decodeJwt(getIdToken());
}
