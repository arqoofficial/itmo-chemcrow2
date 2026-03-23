import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bot, Loader2 } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"

import { OpenAPI } from "@/client"
import { ConversationsService } from "@/client/chatService"
import type { ArticleDownloadJob, ChatMessagePublic, HazardChemical, ToolCallInfo } from "@/client/chatTypes"
import { ArticleDownloadsCard } from "./ArticleDownloadsCard"
import {
  type StreamingState,
  useConversationSSE,
} from "@/hooks/useConversationSSE"
import { ChatInput } from "./ChatInput"
import { HazardWarning } from "./HazardWarning"
import { MarkdownContent } from "./MarkdownContent"
import { MessageBubble } from "./MessageBubble"
import { ToolCallCard } from "./ToolCallCard"

interface ChatWindowProps {
  conversationId: string
}

function ThinkingIndicator({ toolCalls = [] }: { toolCalls?: ToolCallInfo[] }) {
  return (
    <div className="flex gap-3 py-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-600">
        <Bot className="h-4 w-4 text-white" />
      </div>
      <div className="flex max-w-[75%] flex-col gap-2">
        {toolCalls.length > 0 && (
          <div className="w-full">
            {toolCalls.map((tc, i) => (
              <ToolCallCard key={`${tc.name}-${JSON.stringify(tc.args)}-${i}`} toolCall={tc} />
            ))}
          </div>
        )}
        <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          <span className="text-sm text-muted-foreground">Думаю…</span>
        </div>
      </div>
    </div>
  )
}

function StreamingBubble({
  content,
  toolCalls = [],
}: {
  content: string
  toolCalls?: ToolCallInfo[]
}) {
  return (
    <div className="flex gap-3 py-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-600">
        <Bot className="h-4 w-4 text-white" />
      </div>
      <div className="flex max-w-[75%] flex-col gap-2">
        {toolCalls.length > 0 && (
          <div className="w-full">
            {toolCalls.map((tc, i) => (
              <ToolCallCard key={`${tc.name}-${JSON.stringify(tc.args)}-${i}`} toolCall={tc} />
            ))}
          </div>
        )}
        <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm leading-relaxed">
          <MarkdownContent content={content} />
          <span className="inline-block h-4 w-1.5 animate-pulse bg-foreground/60" />
        </div>
      </div>
    </div>
  )
}

export function ChatWindow({ conversationId }: ChatWindowProps) {
  const queryClient = useQueryClient()
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [localMessages, setLocalMessages] = useState<ChatMessagePublic[]>([])
  const [pendingToolCalls, setPendingToolCalls] = useState<ToolCallInfo[]>([])
  const [hazardChemicals, setHazardChemicals] = useState<HazardChemical[]>([])
  const [articleDownloadBatches, setArticleDownloadBatches] = useState<ArticleDownloadJob[][]>([])
  const [sseEnabled, setSseEnabled] = useState(false)
  const [isRecovering, setIsRecovering] = useState(false)
  const messageCountBeforeSend = useRef(0)

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
    setIsRecovering(false)
  }, [])

  const { data, isLoading } = useQuery({
    queryKey: ["messages", conversationId],
    queryFn: () =>
      ConversationsService.listMessages({
        conversationId,
        limit: 200,
      }),
  })

  const { data: persistedJobs } = useQuery({
    queryKey: ["article-jobs", conversationId],
    queryFn: async () => {
      const token =
        typeof OpenAPI.TOKEN === "function"
          ? await OpenAPI.TOKEN({} as never)
          : (OpenAPI.TOKEN ?? "")
      const resp = await fetch(`/api/v1/articles/conversations/${conversationId}/jobs`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!resp.ok) return [] as ArticleDownloadJob[]
      return resp.json() as Promise<ArticleDownloadJob[]>
    },
    staleTime: Infinity,
  })

  useEffect(() => {
    if (persistedJobs && persistedJobs.length > 0) {
      setArticleDownloadBatches([persistedJobs])
    }
  }, [persistedJobs])

  useEffect(() => {
    setLocalMessages([])
    setPendingToolCalls([])
    setHazardChemicals([])
    setArticleDownloadBatches([])
    stopPolling()
  }, [conversationId, stopPolling])

  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  useEffect(() => {
    if (data?.data) {
      setLocalMessages((prev) => {
        const serverIds = new Set(data.data.map((m) => m.id))
        const localOnly = prev.filter(
          (m) => m.id && !serverIds.has(m.id),
        )
        if (localOnly.length === 0) return data.data
        return [...data.data, ...localOnly]
      })
      if (isRecovering && data.data.length > messageCountBeforeSend.current) {
        stopPolling()
      }
    }
  }, [data, isRecovering, stopPolling])

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() =>
      bottomRef.current?.scrollIntoView({ behavior: "smooth" }),
    )
  }, [])

  useEffect(scrollToBottom, [localMessages, pendingToolCalls, scrollToBottom])

  const handleSSEMessage = useCallback(
    (msg: ChatMessagePublic) => {
      setLocalMessages((prev) => {
        if (prev.some((m) => m.id === msg.id)) return prev
        return [...prev, msg]
      })
      setPendingToolCalls([])
      setSseEnabled(false)
      stopPolling()
      queryClient.invalidateQueries({ queryKey: ["messages", conversationId] })
      queryClient.invalidateQueries({ queryKey: ["conversations"] })
    },
    [conversationId, queryClient, stopPolling],
  )

  const handleToolCall = useCallback((tc: ToolCallInfo) => {
    setPendingToolCalls((prev) => {
      const tcKey = `${tc.name}:${JSON.stringify(tc.args)}`
      const existingIndex = prev.findIndex(
        (item) => `${item.name}:${JSON.stringify(item.args)}` === tcKey,
      )

      if (existingIndex === -1) return [...prev, tc]

      const next = [...prev]
      next[existingIndex] = { ...next[existingIndex], ...tc }
      return next
    })
  }, [])

  const handleHazards = useCallback((chemicals: HazardChemical[]) => {
    if (chemicals.length > 0) setHazardChemicals(chemicals)
  }, [])

  const handleArticleDownloads = useCallback((jobs: ArticleDownloadJob[]) => {
    if (jobs.length > 0) {
      setArticleDownloadBatches((prev) => [...prev, jobs])
    }
  }, [])

  const handleError = useCallback(
    (_err: string) => {
      setSseEnabled(false)
      setIsRecovering(true)
      queryClient.invalidateQueries({
        queryKey: ["messages", conversationId],
      })

      if (pollTimerRef.current) return
      let attempts = 0
      pollTimerRef.current = setInterval(() => {
        attempts++
        queryClient.invalidateQueries({
          queryKey: ["messages", conversationId],
        })
        if (attempts >= 15) {
          stopPolling()
        }
      }, 2000)
    },
    [conversationId, queryClient, stopPolling],
  )

  const { streamingState, streamingContent } = useConversationSSE({
    conversationId,
    enabled: sseEnabled,
    onMessage: handleSSEMessage,
    onToolCall: handleToolCall,
    onHazards: handleHazards,
    onArticleDownloads: handleArticleDownloads,
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
      setHazardChemicals([])
      messageCountBeforeSend.current = localMessages.length + 1
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
    isRecovering ||
    (["connecting", "thinking", "streaming"] as StreamingState[]).includes(
      streamingState,
    )

  return (
    <div className="relative flex h-full flex-col">
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

            {articleDownloadBatches.map((batch, i) => (
              <ArticleDownloadsCard key={i} jobs={batch} />
            ))}

            {(streamingState === "thinking" || isRecovering) && (
              <ThinkingIndicator toolCalls={pendingToolCalls} />
            )}

            {streamingState === "streaming" && streamingContent && (
              <StreamingBubble
                content={streamingContent}
                toolCalls={pendingToolCalls}
              />
            )}

            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <ChatInput onSend={handleSend} disabled={isWaiting} />

      <HazardWarning chemicals={hazardChemicals} />
    </div>
  )
}
