import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ArticleDownloadsCard } from "../ArticleDownloadsCard"

// Stub lucide-react icons
vi.mock("lucide-react", () => ({
  CheckCircle2: () => <span>CheckCircle2</span>,
  Loader2: () => <span>Loader2</span>,
  RefreshCw: ({ className }: { className?: string }) => (
    <span className={className}>RefreshCw</span>
  ),
  XCircle: () => <span>XCircle</span>,
}))

// Stub @/client
vi.mock("@/client", () => ({
  OpenAPI: { TOKEN: "test-token" },
}))

// Stub Card to avoid shadcn import issues
vi.mock("@/components/ui/card", () => ({
  Card: ({
    children,
    className,
  }: {
    children: React.ReactNode
    className?: string
  }) => (
    <div data-testid="card" className={className}>
      {children}
    </div>
  ),
}))

// Stub cn utility
vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const makeJob = (jobId: string, doi: string) => ({ job_id: jobId, doi })

type FetchResponse = {
  status: string
  url?: string | null
  error?: string | null
  job_id?: string
}

function mockFetch(responses: Record<string, FetchResponse>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const matched = Object.entries(responses).find(([key]) =>
        url.includes(key),
      )
      if (matched) {
        return {
          ok: true,
          json: async () => matched[1],
        }
      }
      return { ok: false, json: async () => ({}) }
    }),
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe("ArticleDownloadsCard", () => {
  it("renders job DOIs", async () => {
    mockFetch({
      "/jobs/job-1": { status: "pending", url: null, error: null },
      "/jobs/job-2": { status: "pending", url: null, error: null },
    })

    render(
      <ArticleDownloadsCard
        jobs={[
          makeJob("job-1", "10.1234/doi-one"),
          makeJob("job-2", "10.5678/doi-two"),
        ]}
        conversationId="conv-abc"
      />,
      { wrapper },
    )

    expect(screen.getByText("10.1234/doi-one")).toBeInTheDocument()
    expect(screen.getByText("10.5678/doi-two")).toBeInTheDocument()
  })

  it("does not show Notify Agent button when all parse succeeded", async () => {
    mockFetch({
      "/jobs/job-1": {
        status: "done",
        url: "http://example.com/1.pdf",
        error: null,
      },
      "/jobs/job-2": {
        status: "done",
        url: "http://example.com/2.pdf",
        error: null,
      },
      "/jobs/job-1/parse-status": {
        job_id: "job-1",
        status: "completed",
        error: null,
      },
      "/jobs/job-2/parse-status": {
        job_id: "job-2",
        status: "completed",
        error: null,
      },
    })

    render(
      <ArticleDownloadsCard
        jobs={[
          makeJob("job-1", "10.1234/doi-one"),
          makeJob("job-2", "10.5678/doi-two"),
        ]}
        conversationId="conv-abc"
      />,
      { wrapper },
    )

    await waitFor(() => {
      expect(
        screen.queryByText("Notify Agent about available papers"),
      ).not.toBeInTheDocument()
    })
  })

  it("shows Notify Agent button when some parse failed and some succeeded", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/parse-status")) {
          const jobId = url.includes("job-1") ? "job-1" : "job-2"
          const status = jobId === "job-1" ? "failed" : "completed"
          return {
            ok: true,
            json: async () => ({ job_id: jobId, status, error: null }),
          }
        }
        if (url.includes("/jobs/job-1") || url.includes("/jobs/job-2")) {
          const jobId = url.includes("job-1") ? "job-1" : "job-2"
          return {
            ok: true,
            json: async () => ({
              status: "done",
              url: `http://example.com/${jobId}.pdf`,
              error: null,
            }),
          }
        }
        return { ok: false, json: async () => ({}) }
      }),
    )

    render(
      <ArticleDownloadsCard
        jobs={[
          makeJob("job-1", "10.1234/doi-one"),
          makeJob("job-2", "10.5678/doi-two"),
        ]}
        conversationId="conv-abc"
      />,
      { wrapper },
    )

    await waitFor(
      () => {
        expect(
          screen.getByText("Notify Agent about available papers"),
        ).toBeInTheDocument()
      },
      { timeout: 5000 },
    )
  })

  it("triggers POST on button click and shows notified state", async () => {
    const fetchMock = vi.fn(async (url: string, opts?: RequestInit) => {
      void opts
      if (url.includes("/trigger-rag-continuation")) {
        return { ok: true, json: async () => ({}) }
      }
      if (url.includes("/parse-status")) {
        const jobId = url.includes("job-1") ? "job-1" : "job-2"
        const status = jobId === "job-1" ? "failed" : "completed"
        return {
          ok: true,
          json: async () => ({ job_id: jobId, status, error: null }),
        }
      }
      if (url.includes("/jobs/job-1") || url.includes("/jobs/job-2")) {
        const jobId = url.includes("job-1") ? "job-1" : "job-2"
        return {
          ok: true,
          json: async () => ({
            status: "done",
            url: `http://example.com/${jobId}.pdf`,
            error: null,
          }),
        }
      }
      return { ok: false, json: async () => ({}) }
    })
    vi.stubGlobal("fetch", fetchMock)

    render(
      <ArticleDownloadsCard
        jobs={[
          makeJob("job-1", "10.1234/doi-one"),
          makeJob("job-2", "10.5678/doi-two"),
        ]}
        conversationId="conv-xyz"
      />,
      { wrapper },
    )

    const button = await screen.findByText(
      "Notify Agent about available papers",
      {},
      { timeout: 5000 },
    )
    await userEvent.click(button)

    // POST was called to the correct URL
    const postCall = fetchMock.mock.calls.find(
      ([url, opts]) =>
        typeof url === "string" &&
        url.includes("/conversations/conv-xyz/trigger-rag-continuation") &&
        opts?.method === "POST",
    )
    expect(postCall).toBeDefined()

    await waitFor(() => {
      expect(
        screen.getByText("Agent notified — analysis will appear shortly."),
      ).toBeInTheDocument()
    })

    // Original button is gone
    expect(
      screen.queryByText("Notify Agent about available papers"),
    ).not.toBeInTheDocument()
  })
})
