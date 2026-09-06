# Phase 9 Compiler Workbench

Phase 9 adds a responsive React and TypeScript interface under `frontend/`. It is
an inspection and review client for the existing FastAPI compiler pipeline, not a
second compiler implementation.

## Architecture

- `src/App.tsx` owns request state, cancellation, source revisions, inspector
  selection, and the explicit correction-apply workflow.
- `src/services/api.ts` is the only HTTP boundary. It calls `/health`, `/analyze`,
  `/correct`, and `/tokens`; typed helpers for `/ast` and `/symbols` are also
  available.
- `src/components/CodeEditor.tsx` configures Monaco as an editing surface. It
  disables suggestions, automatic bracket/quote insertion, formatting, and other
  language assistance. The only diagnostic markers it renders are supplied by
  backend responses under the `backend` marker owner.
- Inspector components render tokens, AST nodes, scopes, symbols, diagnostics,
  correction history, ML confidence, Groq fallback state, and parser validation.

The correction workflow never mutates the source automatically. `Correct` asks
the backend for a compiler-validated proposal and shows it in a read-only editor.
The source changes only after the user selects **Apply Corrected Code**, after
which the new source is analyzed again by the backend.

## Configuration and commands

```powershell
cd frontend
Copy-Item .env.example .env.local
npm install
npm run dev
```

`VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000`. Never place Groq or other
server credentials in a `VITE_` variable because Vite exposes those values to the
browser bundle.

Production and integration verification:

```powershell
cd frontend
npm run build
npm test
```

The Playwright suite starts both Vite and FastAPI, uses the real backend for the
main analysis and correction journeys, and mocks only explicit failure/delay
cases. It verifies backend health, Monaco markers and hover messages, tokens, AST,
symbols, correction review/apply behavior, stale-request cancellation, safe error
messages, and narrow-screen layout.
