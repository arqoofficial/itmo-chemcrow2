import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react"
import { useState } from "react"

import { OpenAPI } from "@/client"
import type { ArticleDownloadJob } from "@/client/chatTypes"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface JobStatus {
  job_id: string
  status: string
  url: string | null
  error: string | null
}

interface ParseStatus {
  job_id: string
  status: string
  error: string | null
}

async function apiFetch(path: string, options?: RequestInit) {
  const token =
    typeof OpenAPI.TOKEN === "function"
      ? await OpenAPI.TOKEN({} as never)
      : (OpenAPI.TOKEN ?? "")
  const resp = await fetch(path, {
    headers: { Authorization: `Bearer ${token}` },
    ...options,
  })
  if (!resp.ok) throw new Error("fetch failed")
  return resp.json()
}

function ParseIndicator({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient()
  const { data } = useQuery<ParseStatus>({
    queryKey: ["parse-status", jobId],
    queryFn: () => apiFetch(`/api/v1/articles/jobs/${jobId}/parse-status`),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      if (s === "completed" || s === "failed") return false
      return 3000
    },
    staleTime: 0,
    retry: 3,
    retryDelay: 3000,
  })

  const retryMutation = useMutation({
    mutationFn: () =>
      apiFetch(`/api/v1/articles/jobs/${jobId}/reparse`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["parse-status", jobId] })
    },
  })

  const s = data?.status
  if (s === "completed") {
    return (
      <span className="flex items-center gap-1 text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="h-3 w-3 shrink-0" />
        parsed
      </span>
    )
  }
  if (s === "failed") {
    return (
      <span className="flex items-center gap-1">
        <span
          className="flex items-center gap-1 text-destructive"
          title={data?.error ?? undefined}
        >
          <XCircle className="h-3 w-3 shrink-0" />
          parse failed
        </span>
        <button
          type="button"
          onClick={() => retryMutation.mutate()}
          disabled={retryMutation.isPending}
          className="flex items-center gap-0.5 text-xs text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
        >
          <RefreshCw className="h-2.5 w-2.5 shrink-0" />
          {retryMutation.isPending ? "retrying…" : "retry"}
        </button>
      </span>
    )
  }
  return (
    <span className="flex items-center gap-1 text-muted-foreground">
      <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
      parsing…
    </span>
  )
}

function ArticleJobRow({ job }: { job: ArticleDownloadJob }) {
  const { data } = useQuery<JobStatus>({
    queryKey: ["article-job", job.job_id],
    queryFn: () => apiFetch(`/api/v1/articles/jobs/${job.job_id}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === "done" || status === "failed") return false
      return 3000
    },
    staleTime: 0,
  })

  const status = data?.status ?? "pending"
  const truncatedDoi =
    job.doi.length > 40 ? `${job.doi.slice(0, 40)}…` : job.doi

  const icon =
    status === "done" ? (
      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
    ) : status === "failed" ? (
      <XCircle className="h-3.5 w-3.5 shrink-0 text-destructive" />
    ) : (
      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
    )

  return (
    <div className="flex flex-col gap-0.5 py-1 text-xs">
      <div className="flex items-center gap-2">
        {icon}
        {status === "done" && data?.url ? (
          <a
            href={data.url}
            target="_blank"
            rel="noopener noreferrer"
            className="truncate text-blue-600 hover:underline dark:text-blue-400"
            title={job.doi}
          >
            {truncatedDoi}
          </a>
        ) : (
          <span className="truncate text-muted-foreground" title={job.doi}>
            {truncatedDoi}
          </span>
        )}
        {status === "done" && <ParseIndicator jobId={job.job_id} />}
      </div>
      {status === "failed" && data?.error && (
        <p className="pl-5 text-destructive/80">{data.error}</p>
      )}
    </div>
  )
}

interface ArticleDownloadsCardProps {
  jobs: ArticleDownloadJob[]
  conversationId: string
}

export function ArticleDownloadsCard({
  jobs,
  conversationId,
}: ArticleDownloadsCardProps) {
  const [notified, setNotified] = useState(false)
  const [notifying, setNotifying] = useState(false)

  const fetchStatusQueries = useQueries({
    queries: jobs.map((job) => ({
      queryKey: ["article-job", job.job_id],
      queryFn: () => apiFetch(`/api/v1/articles/jobs/${job.job_id}`),
      refetchInterval: (query: { state: { data?: JobStatus } }) => {
        const s = query.state.data?.status
        return s === "done" || s === "failed" ? false : 3000
      },
      staleTime: 0,
    })),
  })

  const doneJobIds = jobs
    .filter((_, i) => fetchStatusQueries[i]?.data?.status === "done")
    .map((j) => j.job_id)

  const parseStatusQueries = useQueries({
    queries: doneJobIds.map((jobId) => ({
      queryKey: ["parse-status", jobId],
      queryFn: () => apiFetch(`/api/v1/articles/jobs/${jobId}/parse-status`),
      refetchInterval: (query: { state: { data?: ParseStatus } }) => {
        const s = query.state.data?.status
        return s === "completed" || s === "failed" ? false : 3000
      },
      staleTime: 0,
    })),
  })

  const allFetchTerminal = fetchStatusQueries.every(
    (q) => q.data?.status === "done" || q.data?.status === "failed",
  )
  const parseStatuses = parseStatusQueries.map((q) => q.data?.status)
  const allParseTerminal =
    doneJobIds.length > 0 &&
    parseStatuses.every((s) => s === "completed" || s === "failed")
  const anyParseFailed = parseStatuses.some((s) => s === "failed")
  const anyParseSucceeded = parseStatuses.some((s) => s === "completed")
  const showNotify =
    allFetchTerminal && allParseTerminal && anyParseFailed && anyParseSucceeded

  const handleNotify = async () => {
    setNotifying(true)
    try {
      await apiFetch(
        `/api/v1/articles/conversations/${conversationId}/trigger-rag-continuation`,
        { method: "POST" },
      )
      setNotified(true)
    } catch {
      // silently ignore — user can retry manually
    } finally {
      setNotifying(false)
    }
  }

  if (jobs.length === 0) return null

  return (
    <Card className="my-2 overflow-hidden border-muted bg-muted/30 p-0">
      <div className="border-b border-muted px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">
          Fetching PDFs…
        </span>
      </div>
      <div className="px-3 py-2">
        {jobs.map((job) => (
          <ArticleJobRow key={job.job_id} job={job} />
        ))}
      </div>
      {showNotify && !notified && (
        <div className="border-t border-muted px-3 py-2">
          <button
            type="button"
            onClick={handleNotify}
            disabled={notifying}
            className="flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
          >
            <RefreshCw className={cn("h-3 w-3", notifying && "animate-spin")} />
            {notifying ? "Notifying…" : "Notify Agent about available papers"}
          </button>
        </div>
      )}
      {notified && (
        <div className="border-t border-muted px-3 py-2">
          <span className="text-xs text-muted-foreground">
            Agent notified — analysis will appear shortly.
          </span>
        </div>
      )}
    </Card>
  )
}
