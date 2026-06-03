# NexusPanel Dashboard

React + Vite + Chakra UI admin interface for NexusPanel.

## Development

```bash
npm install
npm run dev
```

Open http://localhost:3000 — API requests proxy to the backend (configure in `vite.config` if needed).

## Production build

```bash
npm run build -- --outDir build --assetsDir statics
```

Artifacts are written to `build/` and served by the FastAPI app under `/dashboard/`.

## Theme

- Design tokens: `chakra.config.ts` (accent teal + indigo, dark-first)
- Layout shell: `src/components/Shell.tsx`
- Login: glass card on gradient background (`src/pages/Login.tsx`)
