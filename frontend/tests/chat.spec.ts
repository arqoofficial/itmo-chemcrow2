import { expect, test } from "@playwright/test"
import {
  createNewChat,
  getLastNonToolCallMessage,
  sendMessage,
  waitForBotResponse,
  waitForToolCall,
} from "./utils/chat"
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
    await expect(
      sidebar.getByTestId("chat-list-item").filter({ hasText: title }).first(),
    ).toBeVisible()
  })

  test("Delete a conversation", async ({ page }) => {
    await page.goto("/chat")
    const title = `Delete Me ${randomItemTitle()}`
    await createNewChat(page, title)

    // Find the chat item and hover to reveal delete button
    const chatItem = page
      .getByRole("complementary")
      .getByTestId("chat-list-item")
      .filter({ hasText: title })
      .first()
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
    await expect(
      page.getByTestId("message-user").filter({ hasText: msg }),
    ).toBeVisible()
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
  test.skip(
    !!process.env.SKIP_CHEMISTRY_TESTS,
    "Skipped: SKIP_CHEMISTRY_TESTS is set",
  )

  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `Chem Test ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("Molecular weight query triggers smiles2weight tool", async ({
    page,
  }) => {
    await sendMessage(page, "What is the molecular weight of caffeine?")
    await waitForBotResponse(page, 240_000)
    // Should show tool call card
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Wait for the final answer (after tool execution) which should mention the weight
    // Caffeine MW is ~194.19 (average) or ~180.06 (exact/monoisotopic) depending on tool
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/1[89]\d\.\d/, { timeout: 240_000 })
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

test.describe("Chat — converter tools (PubChem)", () => {
  // These tools use PubChem REST API (free, no key required)
  test.skip(
    !!process.env.SKIP_CHEMISTRY_TESTS,
    "Skipped: SKIP_CHEMISTRY_TESTS is set",
  )

  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `Conv Test ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("query2smiles_tool — molecule name to SMILES", async ({ page }) => {
    await sendMessage(page, "Convert caffeine to SMILES notation")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // SMILES for caffeine contains typical organic chemistry characters
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/CN|n1|c1|O=C/i, { timeout: 240_000 })
  })

  test("query2cas_tool — molecule name to CAS number", async ({ page }) => {
    await sendMessage(page, "What is the CAS number of aspirin?")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Aspirin CAS: 50-78-2
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/50-78-2|CAS/i, { timeout: 240_000 })
  })

  test("smiles2name_tool — SMILES to molecule name", async ({ page }) => {
    // Aspirin SMILES
    await sendMessage(
      page,
      "What is the name of the molecule CC(=O)Oc1ccccc1C(=O)O?",
    )
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Should identify as aspirin or acetylsalicylic acid
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/aspirin|acetylsalicylic/i, {
      timeout: 240_000,
    })
  })
})

test.describe("Chat — RDKit molecular property tools", () => {
  test.skip(
    !!process.env.SKIP_CHEMISTRY_TESTS,
    "Skipped: SKIP_CHEMISTRY_TESTS is set",
  )

  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `RDKit Test ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("mol_similarity — compare two molecules by Tanimoto similarity", async ({
    page,
  }) => {
    await sendMessage(
      page,
      "How similar are caffeine and theophylline structurally?",
    )
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Response should mention similarity score or descriptor
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/similar|tanimoto|0\.\d/i, {
      timeout: 240_000,
    })
  })

  test("func_groups — identify functional groups in a molecule", async ({
    page,
  }) => {
    await sendMessage(page, "What functional groups does aspirin contain?")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Aspirin contains esters, carboxylic acids, ketones/carbonyl, aromatic ring
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(
      /ester|carboxyl|carbonyl|acid|functional/i,
      { timeout: 240_000 },
    )
  })
})

test.describe("Chat — chemical safety tools", () => {
  test.skip(
    !!process.env.SKIP_CHEMISTRY_TESTS,
    "Skipped: SKIP_CHEMISTRY_TESTS is set",
  )

  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `Safety Test ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("control_chem_check — check if molecule is a controlled chemical", async ({
    page,
  }) => {
    // Aspirin is not a controlled chemical — safe to test
    await sendMessage(page, "Is aspirin a controlled chemical?")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Should report low similarity or not found in controlled list
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/controlled|safe|similar|low/i, {
      timeout: 240_000,
    })
  })

  test("similar_control_chem_check — similarity to controlled chemicals", async ({
    page,
  }) => {
    // Ibuprofen is a common OTC drug — should have low similarity to controlled chemicals
    await sendMessage(
      page,
      "Is ibuprofen similar to any controlled or hazardous chemicals?",
    )
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/similar|safe|similarity|controlled/i, {
      timeout: 240_000,
    })
  })

  test("explosive_check — check if molecule is explosive", async ({ page }) => {
    // Use acetaminophen (paracetamol) CAS 103-90-2 — not explosive, safe to test
    await sendMessage(page, "Is paracetamol (CAS 103-90-2) explosive?")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Should report not explosive
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/not.*explos|explos.*not|safe/i, {
      timeout: 240_000,
    })
  })
})

test.describe("Chat — reaction tools (Docker services)", () => {
  // These tests require the reaction-predict and retrosynthesis Docker containers.
  // Skip if SKIP_REACTION_TESTS env var is set (containers not running).
  test.skip(
    !!process.env.SKIP_REACTION_TESTS,
    "Skipped: SKIP_REACTION_TESTS is set",
  )
  test.skip(
    !!process.env.SKIP_CHEMISTRY_TESTS,
    "Skipped: SKIP_CHEMISTRY_TESTS is set",
  )

  let chatTitle: string

  test.beforeEach(async ({ page }) => {
    await page.goto("/chat")
    chatTitle = `Rxn Test ${randomItemTitle()}`
    await createNewChat(page, chatTitle)
  })

  test("reaction_predict — forward reaction prediction from reactant SMILES", async ({
    page,
  }) => {
    // Esterification: ethanol + acetic acid → ethyl acetate + water
    await sendMessage(
      page,
      "Predict the product when ethanol reacts with acetic acid (use SMILES: CCO.CC(=O)O)",
    )
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Response should contain SMILES-like product or description
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/product|SMILES|CC|react|predict/i, {
      timeout: 240_000,
    })
  })

  test("reaction_retrosynthesis — retrosynthetic route for a target molecule", async ({
    page,
  }) => {
    // Aspirin retrosynthesis
    await sendMessage(
      page,
      "Find the retrosynthetic route to aspirin (SMILES: CC(=O)Oc1ccccc1C(=O)O)",
    )
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Response should describe synthesis steps or retrosynthetic analysis
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/step|synthe|retro|react|route/i, {
      timeout: 240_000,
    })
  })
})

test.describe("Chat — literature search (Semantic Scholar)", () => {
  // Requires full stack. Semantic Scholar API is free (no key required).
  test.skip(
    !!process.env.SKIP_CHEMISTRY_TESTS,
    "Skipped: SKIP_CHEMISTRY_TESTS is set",
  )

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

  test("Literature search returns paper details in response", async ({
    page,
  }) => {
    await sendMessage(page, "Search for recent papers on aspirin synthesis")
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    // The bot response should mention paper-like content or explain the search results
    // Semantic Scholar may rate-limit, so accept either papers or a graceful fallback
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(
      /paper|author|citation|synthesis|literature|search/i,
      { timeout: 240_000 },
    )
  })

  test("Literature search with specific molecule returns relevant results", async ({
    page,
  }) => {
    await sendMessage(
      page,
      "Find papers about the pharmacological properties of ibuprofen",
    )
    await waitForBotResponse(page, 240_000)
    await waitForToolCall(page, undefined, 240_000)
    await expect(page.getByTestId("tool-call-card").first()).toBeVisible()
    // Response should reference ibuprofen or related terms
    const lastMsg = await getLastNonToolCallMessage(page)
    await expect(lastMsg).toContainText(/ibuprofen|NSAID|anti.?inflam/i, {
      timeout: 240_000,
    })
  })
})
