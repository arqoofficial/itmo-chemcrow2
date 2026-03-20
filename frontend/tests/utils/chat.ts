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
