import { fetchEventSource } from "@microsoft/fetch-event-source"
import { renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it, type Mock, vi } from "vitest"
import { useConversationSSE } from "../useConversationSSE"

vi.mock("@microsoft/fetch-event-source", () => ({
  EventStreamContentType: "text/event-stream",
  fetchEventSource: vi.fn(),
}))

vi.mock("@/client", () => ({
  OpenAPI: { BASE: "", TOKEN: "test-token" },
}))

// requestAnimationFrame is not available in jsdom
globalThis.requestAnimationFrame = (cb: FrameRequestCallback) => {
  cb(0)
  return 0
}
globalThis.cancelAnimationFrame = vi.fn()

type OnmessageHandler = (ev: { event: string; data: string }) => void

function captureOnmessage(): OnmessageHandler {
  const mockFetch = fetchEventSource as Mock
  // fetchEventSource is called inside a .then(), so we need to call the handler manually
  let captured: OnmessageHandler | undefined

  mockFetch.mockImplementation(
    (_url: string, opts: { onmessage?: OnmessageHandler }) => {
      captured = opts.onmessage
      return Promise.resolve()
    },
  )

  return (ev) => {
    if (captured) captured(ev)
  }
}

describe("useConversationSSE — background callbacks", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("calls onBackgroundUpdate when background_update event arrives", async () => {
    const dispatch = captureOnmessage()
    const onBackgroundUpdate = vi.fn()

    renderHook(() =>
      useConversationSSE({
        conversationId: "conv-1",
        enabled: true,
        onBackgroundUpdate,
      }),
    )

    // Wait for the getToken().then() to resolve
    await Promise.resolve()

    dispatch({ event: "background_update", data: "{}" })
    expect(onBackgroundUpdate).toHaveBeenCalledTimes(1)
  })

  it("calls onBackgroundError with detail when background_error event arrives", async () => {
    const dispatch = captureOnmessage()
    const onBackgroundError = vi.fn()

    renderHook(() =>
      useConversationSSE({
        conversationId: "conv-1",
        enabled: true,
        onBackgroundError,
      }),
    )

    await Promise.resolve()

    dispatch({
      event: "background_error",
      data: JSON.stringify({
        detail: "S2 rate limit exceeded",
        retry_available: true,
      }),
    })
    expect(onBackgroundError).toHaveBeenCalledWith("S2 rate limit exceeded")
  })

  it("calls onBackgroundError with fallback message when detail is missing", async () => {
    const dispatch = captureOnmessage()
    const onBackgroundError = vi.fn()

    renderHook(() =>
      useConversationSSE({
        conversationId: "conv-1",
        enabled: true,
        onBackgroundError,
      }),
    )

    await Promise.resolve()

    dispatch({ event: "background_error", data: "{}" })
    expect(onBackgroundError).toHaveBeenCalledWith("Background error")
  })
})
