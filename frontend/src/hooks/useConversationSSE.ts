import {
  EventStreamContentType,
  fetchEventSource,
} from "@microsoft/fetch-event-source"
import { useCallback, useEffect, useRef, useState } from "react"

import { OpenAPI } from "@/client"
import type { ChatMessagePublic, ToolCallInfo } from "@/client/chatTypes"

export type StreamingState = "idle" | "connecting" | "thinking" | "streaming"

interface UseConversationSSEOptions {
  conversationId: string
  enabled?: boolean
  onMessage?: (msg: ChatMessagePublic) => void
  onToolCall?: (tc: ToolCallInfo) => void
  onError?: (err: string) => void
}

export function useConversationSSE({
  conversationId,
  enabled = true,
  onMessage,
  onToolCall,
  onError,
}: UseConversationSSEOptions) {
  const [streamingState, setStreamingState] = useState<StreamingState>("idle")
  const [streamingContent, setStreamingContent] = useState("")
  const abortRef = useRef<AbortController | null>(null)
  const callbacksRef = useRef({ onMessage, onToolCall, onError })
  callbacksRef.current = { onMessage, onToolCall, onError }

  const connect = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()

    const ctrl = new AbortController()
    abortRef.current = ctrl
    setStreamingState("connecting")
    setStreamingContent("")

    const base = OpenAPI.BASE || ""
    const url = `${base}/api/v1/events/conversations/${conversationId}`

    const getToken = async () => {
      if (typeof OpenAPI.TOKEN === "function") return await OpenAPI.TOKEN({} as never)
      return OpenAPI.TOKEN ?? ""
    }

    getToken().then((token) => {
      fetchEventSource(url, {
        signal: ctrl.signal,
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: EventStreamContentType,
        },
        onopen: async (response) => {
          if (
            response.ok &&
            response.headers.get("content-type")?.includes(EventStreamContentType)
          ) {
            return
          }
          throw new Error(`SSE connection failed: ${response.status}`)
        },
        onmessage: (ev) => {
          const eventType = ev.event || "message"

          try {
            const data = ev.data ? JSON.parse(ev.data) : {}

            switch (eventType) {
              case "connected":
                setStreamingState("idle")
                break
              case "thinking":
                setStreamingState("thinking")
                break
              case "token":
                setStreamingState("streaming")
                setStreamingContent((prev) => prev + (data.content ?? ""))
                break
              case "message":
                if (data.id && data.content != null) {
                  setStreamingState("idle")
                  setStreamingContent("")
                  callbacksRef.current.onMessage?.(data as ChatMessagePublic)
                }
                break
              case "tool_call":
                callbacksRef.current.onToolCall?.(data as ToolCallInfo)
                break
              case "error":
                setStreamingState("idle")
                callbacksRef.current.onError?.(data.detail ?? "Unknown error")
                break
            }
          } catch {
            /* ignore parse errors for ping frames */
          }
        },
        onerror: (err) => {
          setStreamingState("idle")
          if (!ctrl.signal.aborted) {
            console.error("SSE error:", err)
            callbacksRef.current.onError?.("Connection lost")
          }
          throw err
        },
        openWhenHidden: true,
      }).catch(() => {
        /* error already handled in onerror / onError callback */
      })
    })
  }, [conversationId])

  const disconnect = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setStreamingState("idle")
    setStreamingContent("")
  }, [])

  useEffect(() => {
    if (enabled && conversationId) {
      connect()
    }
    return () => disconnect()
  }, [enabled, conversationId, connect, disconnect])

  return { streamingState, streamingContent, reconnect: connect, disconnect }
}
