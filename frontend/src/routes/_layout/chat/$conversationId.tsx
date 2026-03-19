import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import { ArrowLeft, Loader2 } from "lucide-react"

import { ConversationsService } from "@/client/chatService"
import { ChatWindow } from "@/components/Chat/ChatWindow"
import { Button } from "@/components/ui/button"

export const Route = createFileRoute("/_layout/chat/$conversationId")({
  component: ConversationPage,
  head: () => ({
    meta: [{ title: "Chat - ChemCrow2" }],
  }),
})

function ConversationPage() {
  const { conversationId } = Route.useParams()

  const { data: conversation, isLoading } = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () =>
      ConversationsService.getConversation({ conversationId }),
  })

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b px-4 py-2.5">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 md:hidden"
          asChild
        >
          <Link to="/chat">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-semibold">
            {conversation?.title ?? "Диалог"}
          </h1>
        </div>
      </header>
      <div className="flex-1 overflow-hidden">
        <ChatWindow conversationId={conversationId} />
      </div>
    </div>
  )
}
