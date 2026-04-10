import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { ChatMessagePublic } from "@/client/chatTypes"
import { MessageBubble } from "../MessageBubble"

vi.mock("../BackgroundMessageCard", () => ({
  BackgroundMessageCard: ({ message }: { message: unknown }) => (
    <div data-testid="background-card">{JSON.stringify(message)}</div>
  ),
}))

// Stub lucide-react icons to avoid SVG rendering issues in tests
vi.mock("lucide-react", () => ({
  Bot: () => <span>Bot</span>,
  User: () => <span>User</span>,
}))

// Stub MarkdownContent — just render the text
vi.mock("../MarkdownContent", () => ({
  MarkdownContent: ({ content }: { content: string }) => <span>{content}</span>,
}))

// Stub ToolCallCard
vi.mock("../ToolCallCard", () => ({
  ToolCallCard: () => <div />,
}))

const makeMsg = (overrides: Partial<ChatMessagePublic>): ChatMessagePublic => ({
  id: "m1",
  conversation_id: "conv-1",
  role: "user",
  content: "Hello",
  tool_calls: null,
  created_at: null,
  metadata: null,
  ...overrides,
})

describe("MessageBubble", () => {
  it("renders data-testid=message-user for role=user (regression)", () => {
    render(<MessageBubble message={makeMsg({ role: "user" })} />)
    expect(screen.getByTestId("message-user")).toBeInTheDocument()
  })

  it("renders data-testid=message-bot for role=assistant (regression)", () => {
    render(
      <MessageBubble
        message={makeMsg({ role: "assistant", content: "Hi there" })}
      />,
    )
    expect(screen.getByTestId("message-bot")).toBeInTheDocument()
  })

  it("renders BackgroundMessageCard for role=background", () => {
    const msg = makeMsg({
      role: "background",
      content: "Found 3 papers",
      metadata: { variant: "info" },
    })
    render(<MessageBubble message={msg} />)
    expect(screen.getByTestId("background-card")).toBeInTheDocument()
    // Verify neither user nor bot bubble was rendered
    expect(screen.queryByTestId("message-user")).not.toBeInTheDocument()
    expect(screen.queryByTestId("message-bot")).not.toBeInTheDocument()
  })
})
