/**
 * Copies text to the clipboard. Uses the Clipboard API on HTTPS/localhost;
 * falls back to execCommand for plain HTTP (non-localhost), where clipboard is unavailable.
 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  if (typeof window === "undefined" || !text) return false

  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // continue to fallback (e.g. Permissions-Policy)
    }
  }

  try {
    const ta = document.createElement("textarea")
    ta.value = text
    ta.setAttribute("readonly", "")
    ta.style.position = "fixed"
    ta.style.left = "-9999px"
    ta.style.top = "0"
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand("copy")
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
