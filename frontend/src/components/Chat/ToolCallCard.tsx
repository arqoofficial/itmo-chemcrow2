import { CheckCircle2, Loader2, XCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { ToolCallInfo } from "@/client/chatTypes"

const statusIcon = {
  running: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />,
  completed: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-destructive" />,
} as const

const RAG_TOOL_NAMES = new Set(["rag_search"])

interface ToolCallCardProps {
  toolCall: ToolCallInfo
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const status = toolCall.status ?? "completed"
  const isRagTool = RAG_TOOL_NAMES.has(toolCall.name)

  return (
    <Card className="my-2 overflow-hidden border-muted bg-muted/30 p-0" data-testid="tool-call-card">
      <div className="flex items-center gap-2 border-b border-muted px-3 py-2">
        {statusIcon[status]}
        <span className="text-xs font-medium">{toolCall.name}</span>
        {isRagTool && (
          <Badge variant="secondary" className="text-[10px] bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20">
            RAG
          </Badge>
        )}
        <Badge variant="outline" className="ml-auto text-[10px]">
          tool
        </Badge>
      </div>

      {Object.keys(toolCall.args).length > 0 && (
        <div className="px-3 py-2">
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap break-all">
            {JSON.stringify(toolCall.args, null, 2)}
          </pre>
        </div>
      )}

      {toolCall.result && (
        <div className="border-t border-muted px-3 py-2">
          <pre className="text-xs whitespace-pre-wrap break-all">
            {toolCall.result}
          </pre>
        </div>
      )}
    </Card>
  )
}
