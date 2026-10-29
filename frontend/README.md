# TestForge AI frontend

The Vite/React UI talks to the FastAPI service at `http://localhost:8000`.
Frontend setup, Windows commands, sandbox details, and the live demo procedure
are documented in the repository [README](../README.md).

From this directory, install the lockfile dependencies and start the UI:

```powershell
npm ci
npm run dev
```

Run frontend checks with `npm test` and `npm run build`. The browser application
does not need an AI provider credential; Meta credentials belong only in
`backend/.env`.
