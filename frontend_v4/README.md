# Baskt Frontend

## Environment Modes

Choose the backend/Cognito environment with Vite modes:

```bash
npm run dev:dev
npm run dev:test
npm run build:dev
npm run build:test
```

Stage and prod scripts are available too, but their real Cognito/API values are
not provisioned yet. Create `frontend_v4/.env.stage.local` or
`frontend_v4/.env.prod.local` from the matching `.example` file before running:

```bash
npm run dev:stage
npm run build:prod
```

Required variables:

```text
VITE_APP_ENV
VITE_API_BASE_URL
VITE_COGNITO_REGION
VITE_COGNITO_USER_POOL_ID
VITE_COGNITO_APP_CLIENT_ID
VITE_COGNITO_DOMAIN
VITE_COGNITO_REDIRECT_SIGN_IN
VITE_COGNITO_REDIRECT_SIGN_OUT
```
