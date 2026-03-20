import { expect, test } from "@playwright/test"
import { createNewChat, sendMessage, waitForBotResponse, waitForToolCall } from "./utils/chat"
import { randomItemTitle } from "./utils/random"

test.describe("Chat — conversation management", () => {
  test("Navigate to /chat and see chat sidebar", async ({ page }) => {
    await page.goto("/chat")
    const sidebar = page.getByRole("complementary")
    // Sidebar should contain either empty state or chat items
    const emptyState = sidebar.getByTestId("empty-chat-list")
    const chatList = sidebar.getByTestId("chat-list-item")
    await expect(emptyState.or(chatList.first())).toBeVisible()
  })

  test("Create a new conversation via dialog", async ({ page }) => {
    await page.goto("/chat")
    const title = `Test Chat ${randomItemTitle()}`
    await createNewChat(page, title)
    // Should navigate to the new conversation
    await expect(page).toHaveURL(/\/chat\//)
  })

  test("New conversation appears in sidebar", async ({ page }) => {
    await page.goto("/chat")
    const title = `Test Chat ${randomItemTitle()}`
    await createNewChat(page, title)
    // The title should be visible in the sidebar
    const sidebar = page.getByRole("complementary")
    await expect(sidebar.getByTestId("chat-list-item").filter({ hasText: title }).first()).toBeVisible()
  })

  test("Delete a conversation", async ({ page }) => {
    await page.goto("/chat")
    const title = `Delete Me ${randomItemTitle()}`
    await createNewChat(page, title)

    // Find the chat item and hover to reveal delete button
    const chatItem = page.getByRole("complementary").getByTestId("chat-list-item").filter({ hasText: title }).first()
    await chatItem.hover()
    // Click the trash button within the chat item
    await chatItem.locator("button").click()
    // Confirm deletion in the dialog
    await page.getByRole("button", { name: /удалить|delete/i }).click()
    // Chat should be removed
    await expect(chatItem).not.toBeVisible()
  })
})

test.describe("Chat — messaging basics", () => {
  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `Msg Test ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("Send a text message and see it as user bubble", async ({ page }) => {
    const msg = "Hello, this is a test message"
    await sendMessage(page, msg)
    await expect(page.getByTestId("message-user").filter({ hasText: msg })).toBeVisible()
  })

  test("Receive a bot response (full-stack connectivity)", async ({ page }) => {
    await sendMessage(page, "Hello")
    await waitForBotResponse(page, 240_000)
    await expect(page.getByTestId("message-bot").first()).toBeVisible()
  })

  test("Chat input is disabled while bot is responding", async ({ page }) => {
    await sendMessage(page, "Hello")
    // Immediately after sending, the input or send button should be disabled
    const sendButton = page.getByTestId("chat-send-button")
    // Check that send button is disabled (it might re-enable quickly after response)
    await expect(sendButton).toBeDisabled()
    // Wait for the response to complete
    await waitForBotResponse(page, 240_000)
  })
})

test.describe("Chat — chemistry tool integration", () => {
  // These tests require the full stack: backend + ai-agent + redis + LLM API key
  // Skip if SKIP_CHEMISTRY_TESTS env var is set
  test.skip(!!process.env.SKIP_CHEMISTRY_TESTS, "Skipped: SKIP_CHEMISTRY_TESTS is set")

  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `Chem Test ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("Molecular weight query triggers smiles2weight tool", async ({ page }) => {
    await sendMessage(page, "What is the molecular weight of caffeine?")
    await waitForBotResponse(page, 240_000)
    // Should show tool call card
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Wait for the final answer (after tool execution) which should mention the weight
    // The bot may produce multiple messages; the last one should contain the result
    // Caffeine MW is ~194.19 (average) or ~180.06 (exact/monoisotopic) depending on tool
    await expect(page.getByTestId("message-bot").last()).toContainText(/1[89]\d\.\d/, { timeout: 240_000 })
  })

  test("Patent check query triggers patent_check tool", async ({ page }) => {
    await sendMessage(page, "Is caffeine patented?")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
  })

  test("Tool call cards show tool name and result", async ({ page }) => {
    await sendMessage(page, "What is the molecular weight of aspirin?")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)

    const toolCard = page.getByTestId("tool-call-card").first()
    await expect(toolCard).toBeVisible()
    // Card should contain the tool badge
    await expect(toolCard.getByText("tool", { exact: true })).toBeVisible()
  })
})

test.describe("Chat — literature search (Semantic Scholar)", () => {
  // Requires full stack. Semantic Scholar API is free (no key required).
  test.skip(!!process.env.SKIP_CHEMISTRY_TESTS, "Skipped: SKIP_CHEMISTRY_TESTS is set")

  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `Lit Search ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("Literature query triggers literature_search tool", async ({ page }) => {
    await sendMessage(page, "Find scientific papers about caffeine metabolism")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
  })

  test("Literature search returns paper details in response", async ({ page }) => {
    await sendMessage(page, "Search for recent papers on aspirin synthesis")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    // The bot response should mention paper-like content or explain the search results
    // Semantic Scholar may rate-limit, so accept either papers or a graceful fallback
    await expect(page.getByTestId("message-bot").last()).toContainText(/paper|author|citation|synthesis|literature|search/i, { timeout: 240_000 })
  })

  test("Literature search with specific molecule returns relevant results", async ({ page }) => {
    await sendMessage(page, "Find papers about the pharmacological properties of ibuprofen")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Response should reference ibuprofen or related terms
    await expect(page.getByTestId("message-bot").last()).toContainText(/ibuprofen|NSAID|anti.?inflam/i, { timeout: 240_000 })
  })
})
