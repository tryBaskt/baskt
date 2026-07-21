const allowedEnvs = new Set(["dev", "test", "stage", "prod"]);

export const appEnv = import.meta.env.VITE_APP_ENV || import.meta.env.MODE || "dev";

if (!allowedEnvs.has(appEnv)) {
  throw new Error(
    `Unsupported VITE_APP_ENV '${appEnv}'. Expected one of: dev, test, stage, prod.`
  );
}

export function requiredEnv(name) {
  const value = import.meta.env[name];

  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`Missing required frontend environment variable: ${name}`);
  }

  return value.trim();
}

export function optionalEnv(name, fallback) {
  const value = import.meta.env[name];
  return typeof value === "string" && value.trim() !== "" ? value.trim() : fallback;
}
