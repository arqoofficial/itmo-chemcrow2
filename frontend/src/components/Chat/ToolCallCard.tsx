import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react"
import { useState } from "react"
import type { ToolCallInfo } from "@/client/chatTypes"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { MarkdownContent } from "./MarkdownContent"

const statusIcon = {
  running: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />,
  completed: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-destructive" />,
} as const

const RAG_TOOL_NAMES = new Set(["rag_search"])

interface PaperResult {
  title: string
  authors: string[]
  abstract: string | null
  year: number | null
  citation_count: number | null
  url: string | null
  doi: string | null
}

interface ToolCallCardProps {
  toolCall: ToolCallInfo
}

function formatPapers(papers: PaperResult[]): string {
  if (!papers.length) return "No papers found."
  return papers
    .map((p, i) => {
      const authors =
        p.authors.slice(0, 3).join(", ") +
        (p.authors.length > 3 ? " et al." : "")
      const doi = p.doi ? `DOI: ${p.doi}` : ""
      const citations =
        p.citation_count != null ? `Citations: ${p.citation_count}` : ""
      const meta = [p.year, doi, citations].filter(Boolean).join(" · ")
      return `**${i + 1}. ${p.title}**\n${authors}\n${meta}\n${p.abstract ?? ""}`
    })
    .join("\n\n---\n\n")
}

export function ToolCallCard({ toolCall }: ToolCallCardProps) {
  const status = toolCall.status ?? "completed"
  const isRagTool = RAG_TOOL_NAMES.has(toolCall.name)
  const isRateLimited =
    toolCall.name === "literature_search" &&
    typeof toolCall.result === "string" &&
    toolCall.result.includes("429")

  const [retryState, setRetryState] = useState<
    "idle" | "loading" | "done" | "error"
  >("idle")
  const [retryResult, setRetryResult] = useState<string | null>(null)

  async function handleDirectRetry() {
    const query = String(toolCall.args.query ?? "")
    setRetryState("loading")
    try {
      const token = localStorage.getItem("access_token")
      const res = await fetch("/api/v1/search/literature", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ query, max_results: 5 }),
      })
      if (res.status === 429) {
        setRetryResult(
          "Still rate-limited by Semantic Scholar. Try again in a moment.",
        )
        setRetryState("error")
        return
      }
      if (!res.ok) {
        const err = await res.text()
        setRetryResult(`Search failed: ${err}`)
        setRetryState("error")
        return
      }
      const data = await res.json()
      setRetryResult(formatPapers(data.papers))
      setRetryState("done")
    } catch (e) {
      setRetryResult(`Network error: ${e}`)
      setRetryState("error")
    }
  }

  return (
    <Card
      className="my-2 overflow-hidden border-muted bg-muted/30 p-0"
      data-testid="tool-call-card"
    >
      <div className="flex items-center gap-2 border-b border-muted px-3 py-2">
        {statusIcon[status]}
        <span className="text-xs font-medium">{toolCall.name}</span>
        {isRagTool && (
          <Badge
            variant="secondary"
            className="text-[10px] bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20"
          >
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

      {status === "running" && toolCall.name === "literature_search" && (
        <div className="flex items-center gap-1.5 border-t border-muted px-3 py-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          Searching… retrying if rate-limited
        </div>
      )}

      {toolCall.result && (
        <div className="border-t border-muted px-3 py-2">
          <MarkdownContent content={toolCall.result} className="text-xs" />
          {isRateLimited && retryState === "idle" && (
            <Button
              variant="outline"
              size="sm"
              className="mt-2 h-7 gap-1.5 text-xs"
              onClick={handleDirectRetry}
            >
              <RefreshCw className="h-3 w-3" />
              Retry search
            </Button>
          )}
          {retryState === "loading" && (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Searching Semantic Scholar…
            </div>
          )}
          {(retryState === "done" || retryState === "error") && retryResult && (
            <div className="mt-3 border-t border-muted pt-2">
              <div className="mb-1 flex items-center gap-1.5">
                {retryState === "done" ? (
                  <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                ) : (
                  <XCircle className="h-3 w-3 text-destructive" />
                )}
                <span className="text-[10px] font-medium text-muted-foreground">
                  Retry result
                </span>
                {retryState === "error" && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto h-5 px-1 text-[10px]"
                    onClick={handleDirectRetry}
                  >
                    <RefreshCw className="h-2.5 w-2.5 mr-1" />
                    Try again
                  </Button>
                )}
              </div>
              <MarkdownContent content={retryResult} className="text-xs" />
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
