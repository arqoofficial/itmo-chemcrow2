import { CheckCircle2, Loader2, XCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { ToolCallInfo } from "@/client/chatTypes"
import { MarkdownContent } from "./MarkdownContent"

const statusIcon = {
  running: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />,
  completed: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-destructive" />,
} as const

interface ToolCallCardProps {
  toolCall: ToolCallInfo
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const status = toolCall.status ?? "completed"

  return (
    <Card className="my-2 overflow-hidden border-muted bg-muted/30 p-0" data-testid="tool-call-card">
      <div className="flex items-center gap-2 border-b border-muted px-3 py-2">
        {statusIcon[status]}
        <span className="text-xs font-medium">{toolCall.name}</span>
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
          <MarkdownContent content={toolCall.result} className="text-xs" />
        </div>
      )}
    </Card>
  )
}
