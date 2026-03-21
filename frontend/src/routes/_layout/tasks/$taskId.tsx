import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Clock,
  MessageCircle,
  Wrench,
} from "lucide-react"

import { TasksService } from "@/client/taskService"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/_layout/tasks/$taskId")({
  component: TaskDetail,
  head: () => ({
    meta: [{ title: "Task Details - ChemCrow2" }],
  }),
})

const statusConfig: Record<string, { label: string; className: string }> = {
  pending: {
    label: "Pending",
    className: "bg-muted text-muted-foreground border-muted-foreground/20",
  },
  queued: {
    label: "Queued",
    className:
      "bg-yellow-500/15 text-yellow-700 border-yellow-500/30 dark:text-yellow-400",
  },
  running: {
    label: "Running",
    className:
      "bg-blue-500/15 text-blue-700 border-blue-500/30 dark:text-blue-400 animate-pulse",
  },
  completed: {
    label: "Completed",
    className:
      "bg-emerald-500/15 text-emerald-700 border-emerald-500/30 dark:text-emerald-400",
  },
  failed: {
    label: "Failed",
    className:
      "bg-red-500/15 text-red-700 border-red-500/30 dark:text-red-400",
  },
  cancelled: {
    label: "Cancelled",
    className:
      "bg-muted text-muted-foreground border-muted-foreground/20 line-through",
  },
}

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return "—"
  return new Date(dateStr).toLocaleString()
}

function tryFormatJson(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function TaskDetail() {
  const { taskId } = Route.useParams()

  const { data: task, isLoading } = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => TasksService.getTask({ taskId }),
  })

  if (isLoading) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (!task) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <h3 className="text-lg font-semibold">Task not found</h3>
        <Button variant="outline" className="mt-4" asChild>
          <Link to="/tasks">Back to Tasks</Link>
        </Button>
      </div>
    )
  }

  const sCfg = statusConfig[task.status] ?? statusConfig.pending

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" className="shrink-0" asChild>
          <Link to="/tasks">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight capitalize">
              {task.task_type.replace(/_/g, " ")}
            </h1>
            <Badge
              variant="outline"
              className={cn("text-[11px]", sCfg.className)}
            >
              {sCfg.label}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground font-mono">{task.id}</p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>Source</CardDescription>
            <CardTitle className="text-sm">
              {task.source === "chat" && task.conversation_id ? (
                <Link
                  to="/chat/$conversationId"
                  params={{ conversationId: task.conversation_id }}
                  className="inline-flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400"
                >
                  <MessageCircle className="size-3.5" />
                  Chat
                </Link>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <Wrench className="size-3.5" />
                  Manual
                </span>
              )}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Created</CardDescription>
            <CardTitle className="text-sm inline-flex items-center gap-1">
              <Clock className="size-3.5" />
              {formatDateTime(task.created_at)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Completed</CardDescription>
            <CardTitle className="text-sm">
              {formatDateTime(task.completed_at)}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Celery Task</CardDescription>
            <CardTitle className="text-xs font-mono truncate">
              {task.celery_task_id ?? "—"}
            </CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Input</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-sm whitespace-pre-wrap break-all bg-muted p-4 rounded-lg overflow-auto max-h-96">
            {tryFormatJson(task.input_data)}
          </pre>
        </CardContent>
      </Card>

      {task.result_data && (
        <Card>
          <CardHeader>
            <CardTitle>Result</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-sm whitespace-pre-wrap break-all bg-muted p-4 rounded-lg overflow-auto max-h-96">
              {tryFormatJson(task.result_data)}
            </pre>
          </CardContent>
        </Card>
      )}

      {task.error && (
        <Card className="border-red-500/30">
          <CardHeader>
            <CardTitle className="text-red-600 dark:text-red-400">
              Error
            </CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="text-sm whitespace-pre-wrap break-all bg-red-500/10 text-red-700 dark:text-red-300 p-4 rounded-lg overflow-auto max-h-96">
              {task.error}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
