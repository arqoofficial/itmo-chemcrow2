import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, Loader2, XCircle } from "lucide-react"

import { OpenAPI } from "@/client"
import type { ArticleDownloadJob } from "@/client/chatTypes"
import { Card } from "@/components/ui/card"

interface JobStatus {
  job_id: string
  status: string
  url: string | null
  error: string | null
}

function ArticleJobRow({ job }: { job: ArticleDownloadJob }) {
  const { data } = useQuery<JobStatus>({
    queryKey: ["article-job", job.job_id],
    queryFn: async () => {
      const token =
        typeof OpenAPI.TOKEN === "function"
          ? await OpenAPI.TOKEN({} as never)
          : (OpenAPI.TOKEN ?? "")
      const resp = await fetch(`/api/v1/articles/jobs/${job.job_id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!resp.ok) throw new Error("fetch failed")
      return resp.json()
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === "done" || status === "failed") return false
      return 3000
    },
    staleTime: 0,
  })

  const status = data?.status ?? "pending"
  const truncatedDoi = job.doi.length > 40 ? `${job.doi.slice(0, 40)}…` : job.doi

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
      </div>
      {status === "failed" && data?.error && (
        <p className="pl-5 text-destructive/80">{data.error}</p>
      )}
    </div>
  )
}

interface ArticleDownloadsCardProps {
  jobs: ArticleDownloadJob[]
}

export function ArticleDownloadsCard({ jobs }: ArticleDownloadsCardProps) {
  if (jobs.length === 0) return null

  return (
    <Card className="my-2 overflow-hidden border-muted bg-muted/30 p-0">
      <div className="border-b border-muted px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">Fetching PDFs…</span>
      </div>
      <div className="px-3 py-2">
        {jobs.map((job) => (
          <ArticleJobRow key={job.job_id} job={job} />
        ))}
      </div>
    </Card>
  )
}
