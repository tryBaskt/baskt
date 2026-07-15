export const cognitoConfig = {
  region: import.meta.env.VITE_COGNITO_REGION || "us-east-1",
  userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || "us-east-1_KtBYQRrRN",
  userPoolWebClientId:
    import.meta.env.VITE_COGNITO_APP_CLIENT_ID || "6aur9l3mc674viv3qkb8lffth8",
  domain:
    import.meta.env.VITE_COGNITO_DOMAIN ||
    "dev-baskt-auth.auth.us-east-1.amazoncognito.com",
  redirectSignIn: import.meta.env.VITE_COGNITO_REDIRECT_SIGN_IN || "http://localhost:5173/oauth2/callback",
  redirectSignOut: import.meta.env.VITE_COGNITO_REDIRECT_SIGN_OUT || "http://localhost:5173/",
};
