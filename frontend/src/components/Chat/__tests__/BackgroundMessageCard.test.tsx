import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi, describe, it, expect, beforeEach } from "vitest"
import { BackgroundMessageCard } from "../BackgroundMessageCard"

// Stub OpenAPI.TOKEN so apiFetch works without a real token
vi.mock("@/client", () => ({ OpenAPI: { TOKEN: "test-token" } }))

const infoMsg = {
  id: "m1", conversation_id: "conv-1", role: "background",
  content: "Found 3 papers on aspirin synthesis", tool_calls: null, created_at: null,
  metadata: { variant: "info" },
}
const errorMsg = {
  ...infoMsg,
  content: "Literature search failed. Please retry.",
  metadata: { variant: "error", retry_available: true },
}

describe("BackgroundMessageCard", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("renders content for info variant", () => {
    render(<BackgroundMessageCard message={infoMsg} />)
    expect(screen.getByText("Found 3 papers on aspirin synthesis")).toBeInTheDocument()
  })

  it("does NOT show Retry button for info variant", () => {
    render(<BackgroundMessageCard message={infoMsg} />)
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument()
  })

  it("shows Retry button for error variant", () => {
    render(<BackgroundMessageCard message={errorMsg} />)
    expect(screen.getByRole("button", { name: /retry search/i })).toBeInTheDocument()
  })

  it("POSTs to retry-s2-search endpoint on retry click", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    vi.stubGlobal("fetch", fetchMock)

    render(<BackgroundMessageCard message={errorMsg} />)
    await userEvent.click(screen.getByRole("button", { name: /retry search/i }))

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/articles/conversations/conv-1/retry-s2-search",
      expect.objectContaining({ method: "POST" }),
    )
    await waitFor(() =>
      expect(screen.getByText(/queued|shortly/i)).toBeInTheDocument()
    )
  })

  it("shows 'expired' message on 410 response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 410 }))

    render(<BackgroundMessageCard message={errorMsg} />)
    await userEvent.click(screen.getByRole("button", { name: /retry search/i }))

    await waitFor(() => expect(screen.getByText(/expired/i)).toBeInTheDocument())
    expect(screen.queryByRole("button", { name: /retry search/i })).not.toBeInTheDocument()
  })
})
