/**
 * Types for the Chat / Conversations API.
 * TODO: remove once the OpenAPI client is regenerated.
 */

export type ConversationPublic = {
  id: string
  user_id: string
  title: string
  created_at: string | null
  updated_at: string | null
}

export type ConversationsPublic = {
  data: ConversationPublic[]
  count: number
}

export type ConversationCreate = {
  title: string
}

export type ConversationUpdate = {
  title?: string | null
}

export type ChatMessagePublic = {
  id: string
  conversation_id: string
  role: string
  content: string
  tool_calls: string | null
  created_at: string | null
}

export type ChatMessagesPublic = {
  data: ChatMessagePublic[]
  count: number
}

export type ChatMessageCreate = {
  role: string
  content: string
}

export type ToolCallInfo = {
  name: string
  args: Record<string, unknown>
  result?: string
  status?: "running" | "completed" | "failed"
}

export type SSEEvent =
  | { event: "connected"; data: { conversation_id: string } }
  | { event: "thinking"; data: Record<string, unknown> }
  | {
      event: "message"
      data: {
        id?: string
        role: string
        content: string
        tool_calls?: string | null
      }
    }
  | {
      event: "token"
      data: { content: string }
    }
  | { event: "tool_call"; data: ToolCallInfo }
  | { event: "error"; data: { detail: string } }
