import {
  Briefcase,
  FlaskConical,
  Home,
  MessageCircle,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  useSidebar,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "Dashboard", path: "/" },
  { icon: MessageCircle, title: "Chat", path: "/chat" },
  { icon: Briefcase, title: "Items", path: "/items" },
  { icon: FlaskConical, title: "Molecule Editor", path: "/molecule-editor" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()
  const { toggleSidebar } = useSidebar()

  const items = currentUser?.is_superuser
    ? [...baseItems, { icon: Users, title: "Admin", path: "/admin" }]
    : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="flex items-center justify-center px-4 py-6 group-data-[collapsible=icon]:px-0">
        <button
          type="button"
          onClick={toggleSidebar}
          className="inline-flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 rounded-lg"
          title="Свернуть/Развернуть"
          aria-label="Свернуть/Развернуть боковое меню"
        >
          <Logo variant="responsive" asLink={false} />
        </button>
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
