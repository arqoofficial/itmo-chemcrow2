import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { ToolCallInfo } from "@/client/chatTypes"
import { ToolCallCard } from "../ToolCallCard"

// Stub lucide-react icons to avoid SVG rendering issues
vi.mock("lucide-react", () => ({
  CheckCircle2: () => <span data-testid="icon-check" />,
  Loader2: () => <span data-testid="icon-loader" />,
  RefreshCw: () => <span data-testid="icon-refresh" />,
  XCircle: () => <span data-testid="icon-xcircle" />,
}))

// Stub MarkdownContent — just render the text
vi.mock("../MarkdownContent", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <span data-testid="markdown-content">{content}</span>
  ),
}))

const makeToolCall = (overrides: Partial<ToolCallInfo>): ToolCallInfo => ({
  name: "some_tool",
  args: {},
  ...overrides,
})

describe("ToolCallCard", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe("basic rendering", () => {
    it("renders tool name", () => {
      const toolCall = makeToolCall({ name: "literature_search", args: { query: "aspirin" }, status: "completed" })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.getByText("literature_search")).toBeInTheDocument()
    })

    it("renders JSON args when args are non-empty", () => {
      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "aspirin", max_results: 5 },
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)
      const pre = document.querySelector("pre")
      expect(pre).toBeInTheDocument()
      expect(pre?.textContent).toContain('"query"')
      expect(pre?.textContent).toContain('"aspirin"')
    })

    it("does not render args section when args is empty", () => {
      const toolCall = makeToolCall({ name: "some_tool", args: {}, status: "completed" })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(document.querySelector("pre")).not.toBeInTheDocument()
    })

    it("renders result via MarkdownContent", () => {
      const toolCall = makeToolCall({
        name: "some_tool",
        args: {},
        result: "Result text",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.getByTestId("markdown-content")).toHaveTextContent("Result text")
    })
  })

  describe("running indicator for literature_search", () => {
    it("shows running message when status=running and name=literature_search", () => {
      const toolCall = makeToolCall({ name: "literature_search", args: {}, status: "running" })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.getByText(/Searching.*retrying if rate-limited/)).toBeInTheDocument()
    })

    it("does not show running message when status=completed", () => {
      const toolCall = makeToolCall({ name: "literature_search", args: {}, status: "completed" })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.queryByText(/Searching.*retrying if rate-limited/)).not.toBeInTheDocument()
    })

    it("does not show running message for other tools with status=running", () => {
      const toolCall = makeToolCall({ name: "rag_search", args: {}, status: "running" })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.queryByText(/Searching.*retrying if rate-limited/)).not.toBeInTheDocument()
    })
  })

  describe("RAG badge for rag_search", () => {
    it("shows RAG badge when name=rag_search", () => {
      const toolCall = makeToolCall({ name: "rag_search", args: {}, status: "completed" })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.getByText("RAG")).toBeInTheDocument()
    })

    it("does not show RAG badge for other tools", () => {
      const toolCall = makeToolCall({ name: "literature_search", args: {}, status: "completed" })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.queryByText("RAG")).not.toBeInTheDocument()
    })
  })

  describe("retry button visibility", () => {
    it("shows retry button when result contains 429 and name=literature_search", () => {
      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "benzene" },
        result: "Error 429: rate limited",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.getByRole("button", { name: /retry search/i })).toBeInTheDocument()
    })

    it("does not show retry button when result is normal text", () => {
      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "benzene" },
        result: "Found 3 papers about benzene.",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.queryByRole("button", { name: /retry search/i })).not.toBeInTheDocument()
    })

    it("does not show retry button when name is not literature_search even if result has 429", () => {
      const toolCall = makeToolCall({
        name: "rag_search",
        args: { query: "benzene" },
        result: "Error 429",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)
      expect(screen.queryByRole("button", { name: /retry search/i })).not.toBeInTheDocument()
    })
  })

  describe("retry flow: loading state (429 response)", () => {
    beforeEach(() => {
      vi.spyOn(Storage.prototype, "getItem").mockReturnValue("fake-token")
    })

    it("shows still rate-limited message when retry returns 429", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        status: 429,
        ok: false,
      })
      vi.stubGlobal("fetch", mockFetch)

      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "aspirin" },
        result: "Error 429: too many requests",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)

      fireEvent.click(screen.getByRole("button", { name: /retry search/i }))

      await waitFor(() => {
        expect(screen.getByText(/Still rate-limited/i)).toBeInTheDocument()
      })
    })

    it("sends fetch with correct URL and auth header", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        status: 429,
        ok: false,
      })
      vi.stubGlobal("fetch", mockFetch)

      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "ethanol" },
        result: "429 rate limited",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)

      fireEvent.click(screen.getByRole("button", { name: /retry search/i }))

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          "/api/v1/search/literature",
          expect.objectContaining({
            method: "POST",
            headers: expect.objectContaining({
              Authorization: "Bearer fake-token",
            }),
          }),
        )
      })
    })
  })

  describe("retry flow: success state", () => {
    beforeEach(() => {
      vi.spyOn(Storage.prototype, "getItem").mockReturnValue("fake-token")
    })

    it("shows formatted paper results on successful retry", async () => {
      const mockPapers = [
        {
          title: "Aspirin Synthesis Study",
          authors: ["Smith, J.", "Doe, A."],
          abstract: "A study about aspirin.",
          year: 2023,
          citation_count: 42,
          url: "https://example.com",
          doi: "10.1234/example",
        },
      ]
      const mockFetch = vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        json: async () => ({ papers: mockPapers }),
      })
      vi.stubGlobal("fetch", mockFetch)

      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "aspirin" },
        result: "429: rate limited",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)

      fireEvent.click(screen.getByRole("button", { name: /retry search/i }))

      await waitFor(() => {
        const contents = screen.getAllByTestId("markdown-content")
        const retryContent = contents.find((el) =>
          el.textContent?.includes("Aspirin Synthesis Study"),
        )
        expect(retryContent).toBeInTheDocument()
      })
    })

    it("shows retry result section header after successful retry", async () => {
      const mockPapers = [
        {
          title: "Test Paper",
          authors: ["Author One"],
          abstract: null,
          year: 2022,
          citation_count: null,
          url: null,
          doi: null,
        },
      ]
      const mockFetch = vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        json: async () => ({ papers: mockPapers }),
      })
      vi.stubGlobal("fetch", mockFetch)

      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "test query" },
        result: "429 error",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)

      fireEvent.click(screen.getByRole("button", { name: /retry search/i }))

      await waitFor(() => {
        expect(screen.getByText("Retry result")).toBeInTheDocument()
      })
    })

    it("hides initial retry button after clicking it", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        status: 429,
        ok: false,
      })
      vi.stubGlobal("fetch", mockFetch)

      const toolCall = makeToolCall({
        name: "literature_search",
        args: { query: "caffeine" },
        result: "429 rate limited",
        status: "completed",
      })
      render(<ToolCallCard toolCall={toolCall} />)

      fireEvent.click(screen.getByRole("button", { name: /retry search/i }))

      await waitFor(() => {
        // The initial "Retry search" button should be gone (replaced by loading/error state)
        expect(screen.queryByRole("button", { name: /retry search/i })).not.toBeInTheDocument()
      })
    })
  })
})
