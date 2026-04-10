import { test, expect, Page } from "@playwright/test"

/**
 * E2E Test Suite: OpenAlex Search Feature
 *
 * These tests verify the complete user workflow for OpenAlex search:
 * 1. User initiates OpenAlex search via chat
 * 2. Search returns immediately with "queued" message
 * 3. Results appear as background message within 30s
 * 4. Agent provides initial analysis
 * 5. Retry button appears if search fails
 * 6. Papers are submitted for download/parsing
 */

const TIMEOUT_10S = 10000
const TIMEOUT_30S = 30000
const TIMEOUT_60S = 60000

test.describe("OpenAlex Search Feature", () => {
  let page: Page

  test.beforeEach(async ({ browser }) => {
    page = await browser.newPage()
    await page.goto("http://localhost:5173/")

    // Login if needed (assuming auth is configured)
    const loginButton = page.locator('button:has-text("Login")')
    if ((await loginButton.count()) > 0) {
      await loginButton.click()
      // Complete auth flow (adjust based on your auth implementation)
      await page.waitForURL(/.*chat.*)
    }
  })

  test("User can initiate OpenAlex search via chat", async () => {
    // 1. Send message requesting OpenAlex search
    const inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Search for papers on green chemistry using OpenAlex")
    await inputField.press("Enter")

    // 2. Verify message was sent
    await expect(
      page.locator('text="Search for papers on green chemistry using OpenAlex"')
    ).toBeVisible()

    // 3. Wait for agent to mention OpenAlex search tool call
    const toolCall = page.locator('text="openalex_search"')
    await expect(toolCall).toBeVisible({ timeout: TIMEOUT_30S })

    // 4. Verify "queued" message appears in tool result
    const queuedMessage = page.locator(
      'text=/queued|background message|results will appear/i'
    )
    await expect(queuedMessage).toBeVisible()
  })

  test("OpenAlex results appear as background message", async () => {
    // 1. Send OpenAlex search
    const inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Find recent papers on molecular docking using OpenAlex")
    await inputField.press("Enter")

    // 2. Wait for results background message to appear
    // Background messages are styled cards with info/error icons
    const backgroundCard = page.locator('[class*="bg-blue-500/5"]')
    await expect(backgroundCard).toBeVisible({ timeout: TIMEOUT_30S })

    // 3. Verify results content contains expected fields
    const resultsText = await backgroundCard.textContent()
    expect(resultsText).toMatch(/OpenAlex|papers|found|title/i)

    // 4. Verify paper titles are visible
    const paperTitles = page.locator('[class*="font-semibold"]')
    await expect(paperTitles.first()).toBeVisible()
  })

  test("Agent provides analysis after results appear", async () => {
    // 1. Send OpenAlex search
    const inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill(
      "Search OpenAlex for papers on protein folding"
    )
    await inputField.press("Enter")

    // 2. Wait for background results message
    const backgroundCard = page.locator('[class*="bg-blue-500/5"]')
    await expect(backgroundCard).toBeVisible({ timeout: TIMEOUT_30S })

    // 3. Wait for agent's follow-up response
    // This should appear after the background message in the chat
    const assistantMessages = page.locator('[class*="flex-start"]')
    const messageCount = await assistantMessages.count()
    expect(messageCount).toBeGreaterThanOrEqual(2) // At least tool response + agent response

    // 4. Verify agent's response mentions analysis/findings
    const latestMessage = assistantMessages.last()
    const responseText = await latestMessage.textContent()
    expect(responseText).toMatch(/analysis|findings|results|papers/i)
  })

  test("OpenAlex failure shows error card with retry button", async () => {
    // This test assumes we can trigger an API error via test setup
    // In a real scenario, this would require mocking the API or using a specific test account

    // 1. Send search that will fail (using invalid API or timeout)
    const inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Search OpenAlex for an impossible query xyz123impossible")
    await inputField.press("Enter")

    // 2. Wait for error background message
    const errorCard = page.locator('[class*="bg-destructive/5"]')
    await expect(errorCard).toBeVisible({ timeout: TIMEOUT_30S })

    // 3. Verify error message is visible
    const errorText = await errorCard.textContent()
    expect(errorText).toMatch(/failed|error|unavailable/i)

    // 4. Verify retry button is present
    const retryButton = errorCard.locator('button:has-text("Retry")')
    await expect(retryButton).toBeVisible()

    // 5. Click retry button
    await retryButton.click()

    // 6. Verify retry message appears
    const retryMessage = errorCard.locator('text=/already in progress|retrying/i')
    await expect(retryMessage).toBeVisible({ timeout: TIMEOUT_10S })
  })

  test("Multiple OpenAlex searches can be queued", async () => {
    // 1. Send first search
    let inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Search OpenAlex for machine learning applications")
    await inputField.press("Enter")

    // 2. Send second search immediately
    inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Also search for quantum chemistry papers")
    await inputField.press("Enter")

    // 3. Both searches should queue without blocking
    const queuedMessages = page.locator('text=/queued|queuing/i')
    await expect(queuedMessages).toHaveCount(2, { timeout: TIMEOUT_30S })

    // 4. Results should eventually appear for both
    const backgroundCards = page.locator('[class*="bg-blue-500/5"]')
    await expect(backgroundCards).toHaveCount(2, { timeout: TIMEOUT_60S })
  })

  test("OpenAlex papers can be downloaded", async () => {
    // 1. Send OpenAlex search
    const inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Find chemistry papers on OpenAlex")
    await inputField.press("Enter")

    // 2. Wait for results
    const backgroundCard = page.locator('[class*="bg-blue-500/5"]')
    await expect(backgroundCard).toBeVisible({ timeout: TIMEOUT_30S })

    // 3. Scroll down to see ArticleDownloadsCard
    const downloadsCard = page.locator('[class*="ArticleDownloads"]')
    if ((await downloadsCard.count()) > 0) {
      await downloadsCard.scrollIntoViewIfNeeded()

      // 4. Verify download status is tracked
      const jobElements = page.locator('[class*="job"]')
      await expect(jobElements.first()).toBeVisible({ timeout: TIMEOUT_30S })

      // 5. Verify status indicators appear
      const statusText = page.locator('text=/pending|downloading|parsing|completed/i')
      await expect(statusText).toBeVisible()
    }
  })

  test("Concurrent searches with same query are blocked", async () => {
    // 1. Send first search
    let inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Search for caffeine synthesis with OpenAlex")
    await inputField.press("Enter")

    // Wait briefly to ensure first request is sent
    await page.waitForTimeout(500)

    // 2. Send identical search again (should be blocked)
    inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Search for caffeine synthesis with OpenAlex")
    await inputField.press("Enter")

    // 3. Verify second request shows 409 conflict message
    const conflictMessage = page.locator(
      'text=/already in progress|duplicate|409/i'
    )
    await expect(conflictMessage).toBeVisible({ timeout: TIMEOUT_10S })
  })

  test("OpenAlex search works alongside S2 search", async () => {
    // 1. Send S2 search
    let inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Search Semantic Scholar for aspirin")
    await inputField.press("Enter")

    // 2. Send OpenAlex search
    inputField = page.locator('input[placeholder*="Type a message"]')
    await inputField.fill("Now search OpenAlex for aspirin")
    await inputField.press("Enter")

    // 3. Both should queue without interference
    const queuedMessages = page.locator('text=/queued/i')
    await expect(queuedMessages).toHaveCount(2, { timeout: TIMEOUT_30S })

    // 4. Both results should appear
    const backgroundCards = page.locator('[class*="bg-blue-500/5"]')
    await expect(backgroundCards).toHaveCount(2, { timeout: TIMEOUT_60S })

    // 5. Verify both result sets contain different sources
    const allText = await page.locator('[class*="bg-blue-500/5"]').allTextContents()
    expect(allText.join("\n")).toMatch(/OpenAlex|Semantic Scholar/i)
  })

  test.afterEach(async () => {
    await page.close()
  })
})
