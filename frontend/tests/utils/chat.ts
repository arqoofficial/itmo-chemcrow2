import type { Page } from "@playwright/test"

export async function createNewChat(page: Page, title: string) {
  // Scope to sidebar to avoid strict mode violation (main area also has a new chat button)
  await page.getByRole("complementary").getByTestId("new-chat-button").click()
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

export async function getLastNonToolCallMessage(page: Page) {
  // Get all bot messages, filter out tool card messages (which show JSON like "toolname{...}")
  // and return the last actual response message
  const allBotMessages = page.getByTestId("message-bot")
  const count = await allBotMessages.count()

  for (let i = count - 1; i >= 0; i--) {
    const msg = allBotMessages.nth(i)
    const text = await msg.textContent()
    // Skip if message contains tool card pattern (JSON-like structure)
    if (text && !text.match(/^\w+tool\s*\{/)) {
      return msg
    }
  }

  // Fallback to last message if all are tool cards
  return allBotMessages.last()
}
