# TargetGraph — Frontend

React 19 + TypeScript + Vite SPA for the [TargetGraph](../README.md) cold-outreach
platform. Feature-sliced; mirrors the FastAPI backend contracts 1:1.

## Stack

TailwindCSS v4 · Radix/shadcn-ui · TanStack Query · React Router · React Hook Form ·
axios · sonner · jsPDF (client-side CV → PDF).

## Develop

```bash
npm install
npm run dev      # http://localhost:5173  (allowlisted in backend CORSSettings)
npm run build    # tsc -b && vite build
npm run lint
```

The backend must be running at `http://localhost:8000` (see [../README.md](../README.md)).

## Structure & conventions

See [../docs/Frontend_Spec.md](../docs/Frontend_Spec.md) for the directory layout and
data flows, and [../CLAUDE.md](../CLAUDE.md) for the binding rules (`type` only — no
`interface`/`any`, controlled components, TanStack Query for server state).

```
src/
  contracts/   backend DTO mirror (type only)
  shared/      axios client, error normalisation, query keys
  components/ui/  shadcn components
  features/    jobs-board · profiles · cover-letters
  pages/       JobsFeedPage · ProfilePage · CoverLettersPage
```
