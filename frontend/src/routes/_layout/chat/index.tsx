import { createFileRoute } from "@tanstack/react-router"
import { Bot, Plus } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { ChatList } from "@/components/Chat/ChatList"
import { NewChatDialog } from "@/components/Chat/NewChatDialog"

export const Route = createFileRoute("/_layout/chat/")({
  component: ChatIndex,
})

function ChatIndex() {
  const [newOpen, setNewOpen] = useState(false)

  return (
    <>
      {/* Mobile: show chat list inline */}
      <div className="block h-full md:hidden">
        <ChatList />
      </div>

      {/* Desktop: empty state */}
      <div className="hidden h-full flex-col items-center justify-center md:flex">
        <div className="rounded-full bg-muted p-5">
          <Bot className="h-10 w-10 text-muted-foreground/60" />
        </div>
        <h2 className="mt-4 text-lg font-semibold">ChemCrow2 Chat</h2>
        <p className="mt-1 max-w-sm text-center text-sm text-muted-foreground">
          Выберите диалог из списка слева или создайте новый, чтобы начать
          общение с AI-ассистентом
        </p>
        <Button className="mt-4 gap-2" onClick={() => setNewOpen(true)}>
          <Plus className="h-4 w-4" />
          Новый диалог
        </Button>
        <NewChatDialog open={newOpen} onOpenChange={setNewOpen} />
      </div>
    </>
  )
}
