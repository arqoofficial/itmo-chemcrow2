import type { ColumnDef } from "@tanstack/react-table"
import { ExternalLink, MessageCircle, Wrench } from "lucide-react"
import { Link } from "@tanstack/react-router"

import type { TaskJobPublic } from "@/client/taskTypes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

const statusConfig: Record<string, { label: string; className: string }> = {
  pending: {
    label: "Pending",
    className: "bg-muted text-muted-foreground border-muted-foreground/20",
  },
  queued: {
    label: "Queued",
    className: "bg-yellow-500/15 text-yellow-700 border-yellow-500/30 dark:text-yellow-400",
  },
  running: {
    label: "Running",
    className: "bg-blue-500/15 text-blue-700 border-blue-500/30 dark:text-blue-400 animate-pulse",
  },
  completed: {
    label: "Completed",
    className: "bg-emerald-500/15 text-emerald-700 border-emerald-500/30 dark:text-emerald-400",
  },
  failed: {
    label: "Failed",
    className: "bg-red-500/15 text-red-700 border-red-500/30 dark:text-red-400",
  },
  cancelled: {
    label: "Cancelled",
    className: "bg-muted text-muted-foreground border-muted-foreground/20 line-through",
  },
}

const toolColors: Record<string, string> = {
  retrosynthesis_multi_step:
    "bg-violet-500/15 text-violet-700 border-violet-500/30 dark:text-violet-400",
  chat: "bg-sky-500/15 text-sky-700 border-sky-500/30 dark:text-sky-400",
  example:
    "bg-orange-500/15 text-orange-700 border-orange-500/30 dark:text-orange-400",
}

const defaultToolColor =
  "bg-slate-500/15 text-slate-700 border-slate-500/30 dark:text-slate-400"

function formatToolName(taskType: string): string {
  return taskType.replace(/_/g, " ")
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export const columns: ColumnDef<TaskJobPublic>[] = [
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => {
      const status = row.original.status
      const cfg = statusConfig[status] ?? statusConfig.pending
      return (
        <Badge variant="outline" className={cn("text-[11px]", cfg.className)}>
          {cfg.label}
        </Badge>
      )
    },
  },
  {
    accessorKey: "task_type",
    header: "Tool",
    cell: ({ row }) => {
      const taskType = row.original.task_type
      const color = toolColors[taskType] ?? defaultToolColor
      return (
        <Badge variant="outline" className={cn("text-[11px] capitalize", color)}>
          <Wrench className="size-3 mr-0.5" />
          {formatToolName(taskType)}
        </Badge>
      )
    },
  },
  {
    accessorKey: "source",
    header: "Source",
    cell: ({ row }) => {
      const { source, conversation_id } = row.original
      if (source === "chat" && conversation_id) {
        return (
          <Link
            to="/chat/$conversationId"
            params={{ conversationId: conversation_id }}
            className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
          >
            <MessageCircle className="size-3" />
            Chat
          </Link>
        )
      }
      return (
        <Badge variant="outline" className="text-[11px] bg-muted text-muted-foreground border-muted-foreground/20">
          Manual
        </Badge>
      )
    },
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ row }) => {
      const created = row.original.created_at
      if (!created) return <span className="text-muted-foreground text-xs">—</span>
      return (
        <span className="text-xs text-muted-foreground" title={new Date(created).toLocaleString()}>
          {timeAgo(created)}
        </span>
      )
    },
  },
  {
    id: "result",
    header: () => <span className="sr-only">Result</span>,
    cell: ({ row }) => {
      const hasResult = row.original.result_data !== null || row.original.error !== null
      return (
        <div className="flex justify-end">
          <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs" asChild>
            <Link to="/tasks/$taskId" params={{ taskId: row.original.id }}>
              <ExternalLink className="size-3" />
              {hasResult ? "View result" : "Details"}
            </Link>
          </Button>
        </div>
      )
    },
  },
]
