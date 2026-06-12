export const cognitoConfig = {
  region: import.meta.env.VITE_COGNITO_REGION || "us-east-1",
  userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || "us-east-1_s3Zazcl9c",
  userPoolWebClientId:
    import.meta.env.VITE_COGNITO_APP_CLIENT_ID || "2erhkkj4a3edt6uu7id5gbqla4",
  domain:
    import.meta.env.VITE_COGNITO_DOMAIN ||
    "us-east-1s3zazcl9c.auth.us-east-1.amazoncognito.com",
  redirectSignIn: import.meta.env.VITE_COGNITO_REDIRECT_SIGN_IN || "http://localhost:5173/oauth2/callback",
  redirectSignOut: import.meta.env.VITE_COGNITO_REDIRECT_SIGN_OUT || "http://localhost:5173/",
};
