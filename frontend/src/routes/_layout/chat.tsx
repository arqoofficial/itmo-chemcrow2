import { createFileRoute, Outlet } from "@tanstack/react-router"

import { ChatList } from "@/components/Chat/ChatList"

export const Route = createFileRoute("/_layout/chat")({
  component: ChatLayout,
  head: () => ({
    meta: [{ title: "Chat - ChemCrow2" }],
  }),
})

function ChatLayout() {
  return (
    <div className="-m-6 flex h-[calc(100vh-4rem)] md:-m-8 md:h-[calc(100vh-4rem)]">
      <aside className="hidden w-72 shrink-0 border-r md:block">
        <ChatList />
      </aside>
      <div className="flex-1">
        <Outlet />
      </div>
    </div>
  )
}
