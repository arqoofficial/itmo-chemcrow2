import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bot, Loader2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { ConversationsService } from "@/client/chatService"
import type { ChatMessagePublic, ToolCallInfo } from "@/client/chatTypes"
import {
  type StreamingState,
  useConversationSSE,
} from "@/hooks/useConversationSSE"
import { ChatInput } from "./ChatInput"
import { MessageBubble } from "./MessageBubble"
import { ToolCallCard } from "./ToolCallCard"

interface ChatWindowProps {
  conversationId: string
}

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-600">
        <Bot className="h-4 w-4 text-white" />
      </div>
      <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        <span className="text-sm text-muted-foreground">Думаю…</span>
      </div>
    </div>
  )
}

function StreamingBubble({ content }: { content: string }) {
  return (
    <div className="flex gap-3 px-4 py-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-600">
        <Bot className="h-4 w-4 text-white" />
      </div>
      <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm leading-relaxed">
        <p className="whitespace-pre-wrap break-words">{content}</p>
        <span className="inline-block h-4 w-1.5 animate-pulse bg-foreground/60" />
      </div>
    </div>
  )
}

export function ChatWindow({ conversationId }: ChatWindowProps) {
  const queryClient = useQueryClient()
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const [localMessages, setLocalMessages] = useState<ChatMessagePublic[]>([])
  const [pendingToolCalls, setPendingToolCalls] = useState<ToolCallInfo[]>([])
  const [sseEnabled, setSseEnabled] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () =>
      ConversationsService.listMessages({
        conversationId,
        limit: 200,
      }),
  })

  useEffect(() => {
    if (data?.data) {
      setLocalMessages(data.data)
    }
  }, [data])

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() =>
      bottomRef.current?.scrollIntoView({ behavior: "smooth" }),
    )
  }, [])

  useEffect(scrollToBottom, [localMessages, scrollToBottom])

  const handleSSEMessage = useCallback(
    (msg: ChatMessagePublic) => {
      setLocalMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev
        return [...prev, msg]
      })
      setPendingToolCalls([])
      setSseEnabled(false)
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
      queryClient.invalidateQueries({ queryKey: ["conversations"] })
    },
    [conversationId, queryClient],
  )

  const handleToolCall = useCallback((tc: ToolCallInfo) => {
    setPendingToolCalls((prev) => [...prev, tc])
  }, [])

  const handleError = useCallback(
    (_err: string) => {
      setSseEnabled(false)
      queryClient.invalidateQueries({
        queryKey: ["messages", conversationId],
      })
    },
    [conversationId, queryClient],
  )

  const { streamingState, streamingContent } = useConversationSSE({
    conversationId,
    enabled: sseEnabled,
    onMessage: handleSSEMessage,
    onToolCall: handleToolCall,
    onError: handleError,
  })

  const sendMutation = useMutation({
    mutationFn: (content: string) =>
      ConversationsService.sendMessage({
        conversationId,
        requestBody: { role: "user", content },
      }),
    onSuccess: (userMsg) => {
      setLocalMessages((prev) => {
        if (prev.some((m) => m.id === userMsg.id)) return prev
        return [...prev, userMsg]
      })
      setSseEnabled(true)
    },
  })

  const handleSend = useCallback(
    (content: string) => {
      sendMutation.mutate(content)
    },
    [sendMutation],
  )

  const isWaiting: boolean =
    sendMutation.isPending ||
    (["connecting", "thinking", "streaming"] as StreamingState[]).includes(
      streamingState,
    )

  return (
    <div className="flex h-full flex-col">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : localMessages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <Bot className="mb-3 h-12 w-12 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">
              Начните диалог, отправив сообщение
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl py-4">
            {localMessages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {pendingToolCalls.map((tc, i) => (
              <div key={`tc-${i}`} className="px-4">
                <ToolCallCard toolCall={tc} />
              </div>
            ))}

            {streamingState === "thinking" && <ThinkingIndicator />}

            {streamingState === "streaming" && streamingContent && (
              <StreamingBubble content={streamingContent} />
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <ChatInput onSend={handleSend} disabled={isWaiting} />
    </div>
  )
}
