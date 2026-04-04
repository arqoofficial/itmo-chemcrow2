import { AlertCircle, Info, RefreshCw } from "lucide-react"
import { useState } from "react"

import { OpenAPI } from "@/client"
import type { ChatMessagePublic } from "@/client/chatTypes"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface BackgroundMessageCardProps {
  message: ChatMessagePublic
}

async function apiFetch(path: string, options?: RequestInit) {
  const token =
    typeof OpenAPI.TOKEN === "function"
      ? await OpenAPI.TOKEN({} as never)
      : (OpenAPI.TOKEN ?? "")
  return fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
    ...options,
  })
}

export function BackgroundMessageCard({ message }: BackgroundMessageCardProps) {
  const variant = (message.metadata?.variant as string) ?? "info"
  const isError = variant === "error"
  const [retrying, setRetrying] = useState(false)
  const [retryMessage, setRetryMessage] = useState<string | null>(null)

  const handleRetry = async () => {
    setRetrying(true)
    setRetryMessage(null)
    try {
      const resp = await apiFetch(
        `/api/v1/articles/conversations/${message.conversation_id}/retry-s2-search`,
        { method: "POST" },
      )
      if (resp.status === 410) {
        setRetryMessage("Search query expired — please start a new search.")
      } else if (resp.ok) {
        setRetryMessage("Search re-queued. Results will appear shortly.")
      } else {
        setRetryMessage("Retry failed. Please try again later.")
      }
    } catch {
      setRetryMessage("Retry failed. Please try again later.")
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="flex gap-3 py-2">
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isError ? "bg-destructive/10" : "bg-blue-500/10",
        )}
      >
        {isError ? (
          <AlertCircle className="h-4 w-4 text-destructive" />
        ) : (
          <Info className="h-4 w-4 text-blue-500" />
        )}
      </div>

      <Card
        className={cn(
          "max-w-[75%] border px-4 py-3 text-sm",
          isError
            ? "border-destructive/20 bg-destructive/5 text-destructive"
            : "border-blue-500/20 bg-blue-500/5 text-muted-foreground",
        )}
      >
        <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>

        {isError && !retryMessage && (
          <button
            type="button"
            onClick={handleRetry}
            disabled={retrying}
            className="mt-2 flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
          >
            <RefreshCw className={cn("h-3 w-3", retrying && "animate-spin")} />
            {retrying ? "Retrying…" : "Retry search"}
          </button>
        )}

        {retryMessage && (
          <p className="mt-2 text-xs text-muted-foreground">{retryMessage}</p>
        )}
      </Card>
    </div>
  )
}
