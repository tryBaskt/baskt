import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const requiredFrontendEnv = [
  "VITE_APP_ENV",
  "VITE_API_BASE_URL",
  "VITE_COGNITO_REGION",
  "VITE_COGNITO_USER_POOL_ID",
  "VITE_COGNITO_APP_CLIENT_ID",
  "VITE_COGNITO_DOMAIN",
  "VITE_COGNITO_REDIRECT_SIGN_IN",
  "VITE_COGNITO_REDIRECT_SIGN_OUT",
];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const missing = requiredFrontendEnv.filter((name) => !env[name]?.trim());

  if (missing.length > 0) {
    throw new Error(
      `Missing frontend env vars for mode '${mode}': ${missing.join(", ")}`
    );
  }

  return {
    base: "./",
    plugins: [react()],
    server: {
      allowedHosts: [".ngrok-free.dev"],
    },
    define: {
      global: "globalThis",
    },
  };
});
