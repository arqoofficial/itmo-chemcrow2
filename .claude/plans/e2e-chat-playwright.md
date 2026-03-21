# ChemCrow2 E2E Testing Plan — Playwright

## Context

The ChemCrow2 tools implementation is complete (43 unit tests passing). Now we need E2E tests for the **chat UI** to verify the full stack works: frontend -> backend -> ai-agent -> tools. The project has a Playwright MCP plugin (`@playwright/mcp`) for interactive browser testing, plus an existing Playwright test suite for auth/items/admin.

**Two phases:**
1. Write Playwright test specs for the chat feature
2. Interactive testing with the Playwright MCP tools against the running app

---

## Task 1: Add `data-testid` attributes to chat components

Chat components have **no** `data-testid` attributes. Existing tests use `getByTestId`, `getByRole`, `getByLabel`, `getByPlaceholder`. We need testids for reliable E2E selectors.

**Files to modify:**

| File | Testids to add |
|------|---------------|
| `frontend/src/components/Chat/ChatList.tsx:44` | `data-testid="new-chat-button"` on Plus button |
| `frontend/src/components/Chat/ChatList.tsx:65` | `data-testid="empty-chat-list"` on empty state div |
| `frontend/src/components/Chat/ChatList.tsx:77` | `data-testid="chat-list-item"` on each `<li>` |
| `frontend/src/components/Chat/ChatInput.tsx:48` | `data-testid="chat-input"` on textarea |
| `frontend/src/components/Chat/ChatInput.tsx:58` | `data-testid="chat-send-button"` on send Button |
| `frontend/src/components/Chat/MessageBubble.tsx:27` | `data-testid="message-bubble"` on outer div, plus `data-testid="message-user"` or `data-testid="message-bot"` based on role |
| `frontend/src/components/Chat/ToolCallCard.tsx:20` | `data-testid="tool-call-card"` on Card |
| `frontend/src/components/Chat/NewChatDialog.tsx:57` | `data-testid="chat-title-input"` on Input |
| `frontend/src/components/Chat/NewChatDialog.tsx:73` | `data-testid="create-chat-button"` on submit Button |

---

## Task 2: Add chat test utilities

**Create:** `frontend/tests/utils/chat.ts`

```typescript
import type { Page } from "@playwright/test"

export async function createNewChat(page: Page, title: string) {
  await page.getByTestId("new-chat-button").click()
  await page.getByTestId("chat-title-input").fill(title)
  await page.getByTestId("create-chat-button").click()
  // Wait for navigation to conversation page
  await page.waitForURL(/\/chat\//)
}

export async function sendMessage(page: Page, message: string) {
  await page.getByTestId("chat-input").fill(message)
  await page.getByTestId("chat-send-button").click()
}

export async function waitForBotResponse(page: Page, timeout = 60_000) {
  // Wait for at least one bot message to appear
  await page.getByTestId("message-bot").first().waitFor({ timeout })
}

export async function waitForToolCall(page: Page, toolName?: string, timeout = 60_000) {
  if (toolName) {
    await page.getByTestId("tool-call-card").filter({ hasText: toolName }).first().waitFor({ timeout })
  } else {
    await page.getByTestId("tool-call-card").first().waitFor({ timeout })
  }
}
```

---

## Task 3: Write chat E2E test specs

**Create:** `frontend/tests/chat.spec.ts`

Tests (authenticated via storageState like other specs):

### Conversation management
- [ ] Navigate to /chat, see empty state or chat list
- [ ] Create a new conversation via NewChatDialog
- [ ] New conversation appears in sidebar
- [ ] Delete a conversation

### Messaging basics
- [ ] Send a text message, see it in the chat as user bubble
- [ ] Receive a bot response (any response, verifies full-stack connectivity)
- [ ] Chat input is disabled while bot is responding

### Chemistry tool integration (requires ai-agent + LLM)
- [ ] "What is the molecular weight of caffeine?" → bot uses `smiles2weight` tool, response contains ~194
- [ ] "Is caffeine patented?" → bot uses `patent_check` tool
- [ ] Tool call cards are visible with tool name and result

> **Note:** Chemistry tests need the full stack running (backend, ai-agent, redis, LLM API key). They should be tagged or in a separate describe block so they can be skipped when only frontend is available.

---

## Task 4: Update Playwright config

**Modify:** `frontend/playwright.config.ts`

- Add a `chat` project that depends on `setup` (same as `chromium`)
- Consider longer timeout for chat tests (LLM responses can be slow): `timeout: 120_000`

---

## Task 5: Interactive testing with Playwright MCP

After writing specs, use the Playwright MCP tools to:
1. Launch browser and navigate to `http://localhost:5173`
2. Log in with superuser credentials
3. Navigate to Chat
4. Create a conversation and send chemistry queries
5. Screenshot results and verify tool usage visually

This is done interactively in conversation, not scripted.

---

## Verification

1. **Unit tests still pass:** `cd services/ai-agent && uv run pytest tests/ -v`
2. **E2E tests pass (frontend only):** `cd frontend && bunx playwright test tests/chat.spec.ts`
3. **Full stack E2E:** `docker compose up -d && cd frontend && bunx playwright test tests/chat.spec.ts`
4. **Interactive:** Use Playwright MCP to browse and visually verify chat + tool usage
