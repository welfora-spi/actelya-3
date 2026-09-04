# ACTELYA 3 — Frontend

Applicazione React di ACTELYA 3. Usa CRA tramite CRACO, Tailwind, componenti Radix/shadcn, React Router e Recharts.

## Configurazione

```powershell
Copy-Item .env.example .env
```

`REACT_APP_BACKEND_URL` indica l'origine del backend senza il suffisso `/api`. Non inserire token o credenziali nelle variabili frontend.

## Comandi

```powershell
yarn install --frozen-lockfile
yarn start
$env:CI="true"; yarn test --watchAll=false
yarn build
```

I test correnti coprono registrazione e onboarding. Sala Riunioni, Reel, autorizzazioni e Social Publishing richiedono ulteriore copertura automatizzata.
