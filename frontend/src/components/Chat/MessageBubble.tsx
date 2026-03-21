import { Bot, User } from "lucide-react"
import { useMemo } from "react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import type { ChatMessagePublic, ToolCallInfo } from "@/client/chatTypes"
import { cn } from "@/lib/utils"
import { MarkdownContent } from "./MarkdownContent"
import { ToolCallCard } from "./ToolCallCard"

interface MessageBubbleProps {
  message: ChatMessagePublic
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user"

  const toolCalls = useMemo<ToolCallInfo[]>(() => {
    if (!message.tool_calls) return []
    try {
      return JSON.parse(message.tool_calls) as ToolCallInfo[]
    } catch {
      return []
    }
  }, [message.tool_calls])

  return (
    <div
      className={cn(
          "flex gap-3 py-3",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
      data-testid={isUser ? "message-user" : "message-bot"}
    >
      <Avatar className="h-8 w-8 shrink-0">
        <AvatarFallback
          className={cn(
            "text-xs",
            isUser
              ? "bg-primary text-primary-foreground"
              : "bg-emerald-600 text-white",
          )}
        >
          {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
        </AvatarFallback>
      </Avatar>

      <div
        className={cn(
          "flex max-w-[75%] flex-col gap-1",
          isUser ? "items-end" : "items-start",
        )}
      >
        {toolCalls.length > 0 && (
          <div className="w-full space-y-1">
            {toolCalls.map((tc, i) => (
              <ToolCallCard key={`${tc.name}-${i}`} toolCall={tc} />
            ))}
          </div>
        )}

        <div
          className={cn(
            "rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground rounded-tr-sm"
              : "bg-muted rounded-tl-sm",
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <MarkdownContent content={message.content} />
          )}
        </div>

        {message.created_at && (
          <span className="px-1 text-[10px] text-muted-foreground">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        )}
      </div>
    </div>
  )
}
