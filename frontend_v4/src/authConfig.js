import { requiredEnv } from "./config/env";

export const cognitoConfig = {
  region: requiredEnv("VITE_COGNITO_REGION"),
  userPoolId: requiredEnv("VITE_COGNITO_USER_POOL_ID"),
  userPoolWebClientId: requiredEnv("VITE_COGNITO_APP_CLIENT_ID"),
  domain: requiredEnv("VITE_COGNITO_DOMAIN"),
  redirectSignIn: requiredEnv("VITE_COGNITO_REDIRECT_SIGN_IN"),
  redirectSignOut: requiredEnv("VITE_COGNITO_REDIRECT_SIGN_OUT"),
};
