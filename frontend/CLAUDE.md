# Frontend

React 19 SPA for chemistry research workflows — molecule drawing, chat, article management.

## Dev Commands

```bash
bun install
bun run dev          # Dev server at localhost:5173

bun run build        # Production build → dist/
bun run test:unit    # Vitest unit tests (fast, no browser)
bun run test:unit:watch  # Watch mode
bun run lint         # Biome lint + format check
bun run generate-client  # Regenerate OpenAPI TypeScript client from running backend

bunx playwright test      # E2E tests (requires backend running)
bunx playwright test --ui # Interactive Playwright UI
```

**IMPORTANT:** Use `bun`, never `npm` or `yarn`.

## Project Structure

```
src/
├── main.tsx              # Entry point
├── routes/               # TanStack Router — one file per route
│   ├── _layout.tsx       # Authenticated layout wrapper
│   ├── login.tsx
│   └── ...
├── components/
│   ├── Chat/             # Chat UI + ToolCallCard (streaming SSE messages)
│   ├── MoleculeEditor/   # Ketcher molecule drawing integration
│   ├── Sidebar/          # Navigation
│   ├── Items/            # Molecule list views
│   ├── Admin/            # Admin panel
│   ├── UserSettings/
│   ├── Common/           # Shared layout components
│   └── ui/               # shadcn/ui base components
├── hooks/                # Custom React hooks
├── lib/                  # Utilities
└── client/               # AUTO-GENERATED — do not edit by hand
```

## Key Patterns

- **Routing:** TanStack Router (file-based). Add new routes as files in `src/routes/`.
- **Data fetching:** TanStack Query (`useQuery`, `useMutation`). Use the generated client from `src/client/`.
- **UI components:** shadcn/ui primitives in `src/components/ui/`. Add new ones via `bunx shadcn add <component>`.
- **Forms:** React Hook Form + Zod schemas for validation.
- **Styling:** Tailwind CSS 4 utility classes — no CSS modules, no inline styles.

## OpenAPI Client

`src/client/` is fully auto-generated from the backend's OpenAPI spec — **never edit it manually**.

To regenerate after backend changes:
```bash
# Backend must be running at localhost:8000
bun run generate-client
```

## Molecule Editor (Ketcher)

- Integration in `src/components/MoleculeEditor/`
- RDKit.js is loaded asynchronously — handle loading state before calling RDKit APIs
- Ketcher instance is accessed via ref, not direct import

## Gotchas

- Unit tests use **Vitest** (not Playwright). Config: `vitest.config.ts`. Uses `@vitejs/plugin-react-swc` (NOT `@vitejs/plugin-react` — project is on vite v7). Test setup: `src/test/setup.ts`.
- Vitest needs React alias deduplication (`test.alias` in `vitest.config.ts`) — frontend and root `node_modules` both have React, causing "invalid hook call" errors without it.
- `vi.mock("@microsoft/fetch-event-source", ...)` — the SSE hook uses `fetchEventSource`, not native `EventSource`. Mock this module in hook tests.
- Linter is **Biome**, not ESLint — `biome.json` is the config. Don't add ESLint configs.
- `src/client/` changes should always be committed alongside backend model changes
- SSE streaming responses from `/chat` are handled in `src/components/Chat/` — don't replace with regular fetch
- E2E tests require both frontend and backend to be running
- React hooks rules: all `useMemo`/`useCallback`/`useQuery` calls must come **before** any early return — move hooks above `if (message.role === "background") return ...` patterns
- `fetchEventSource` call is inside a `.then()` — in tests, `await Promise.resolve()` after `renderHook` before dispatching synthetic SSE events to the captured `onmessage`
- When mocking `fetch` with URL-based dispatch, check longer/more-specific paths first (e.g. `/parse-status` before `/jobs/:id` since parse URL contains the job ID)
- `waitFor` default timeout (1000ms) can be too short for TanStack Query with sequential round-trips — use `{ timeout: 5000 }` for two-hop queries (fetch status → parse status)
- Mock `MarkdownContent` in component tests (`vi.mock("../MarkdownContent", ...)`) — otherwise rendered content is opaque for text assertions
- `vi.spyOn(Storage.prototype, "getItem")` must be set up in `beforeEach` within each `describe` block that tests fetch calls — leaks across groups otherwise
