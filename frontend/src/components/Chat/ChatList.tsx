import { useQuery } from "@tanstack/react-query"
import { Link, useParams } from "@tanstack/react-router"
import { MessageSquare, Plus, Trash2 } from "lucide-react"
import { useState } from "react"

import { ConversationsService } from "@/client/chatService"
import type { ConversationPublic } from "@/client/chatTypes"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { DeleteChatDialog } from "./DeleteChatDialog"
import { NewChatDialog } from "./NewChatDialog"

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return ""
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return "только что"
  if (mins < 60) return `${mins} мин`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} ч`
  const days = Math.floor(hours / 24)
  return `${days} д`
}

export function ChatList() {
  const params = useParams({ strict: false })
  const activeId = (params as Record<string, string | undefined>)
    .conversationId

  const [newOpen, setNewOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] =
    useState<ConversationPublic | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => ConversationsService.listConversations({ limit: 50 }),
  })

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold">Чаты</h2>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setNewOpen(true)}
          data-testid="new-chat-button"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full rounded-lg" />
            ))}
          </div>
        ) : !data?.data.length ? (
          <div className="flex flex-col items-center justify-center py-12 text-center" data-testid="empty-chat-list">
            <MessageSquare className="mb-3 h-10 w-10 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">Нет диалогов</p>
            <Button
              variant="link"
              size="sm"
              className="mt-1"
              onClick={() => setNewOpen(true)}
            >
              Создать первый
            </Button>
          </div>
        ) : (
          <ul className="space-y-0.5 p-2">
            {data.data.map((conv) => (
              <li key={conv.id} className="group relative" data-testid="chat-list-item">
                <Link
                  to="/chat/$conversationId"
                  params={{ conversationId: conv.id }}
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors",
                    "hover:bg-muted/70",
                    activeId === conv.id && "bg-muted font-medium",
                  )}
                >
                  <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{conv.title}</p>
                    <p className="text-[10px] text-muted-foreground">
                      {timeAgo(conv.updated_at ?? conv.created_at)}
                    </p>
                  </div>
                </Link>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    setDeleteTarget(conv)
                  }}
                  className="absolute top-1/2 right-2 -translate-y-1/2 rounded-md p-1 opacity-0 transition-opacity hover:bg-destructive/10 group-hover:opacity-100"
                >
                  <Trash2 className="h-3.5 w-3.5 text-destructive" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <NewChatDialog open={newOpen} onOpenChange={setNewOpen} />
      <DeleteChatDialog
        conversation={deleteTarget}
        onClose={() => setDeleteTarget(null)}
      />
    </div>
  )
}
