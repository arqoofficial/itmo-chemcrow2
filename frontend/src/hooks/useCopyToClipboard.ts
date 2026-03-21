// source: https://usehooks-ts.com/react-hook/use-copy-to-clipboard
import { useCallback, useState } from "react"

import { copyTextToClipboard } from "@/lib/clipboard"

type CopiedValue = string | null

type CopyFn = (text: string) => Promise<boolean>

export function useCopyToClipboard(): [CopiedValue, CopyFn] {
  const [copiedText, setCopiedText] = useState<CopiedValue>(null)

  const copy: CopyFn = useCallback(async (text) => {
    const ok = await copyTextToClipboard(text)
    if (ok) {
      setCopiedText(text)
      setTimeout(() => setCopiedText(null), 2000)
    } else {
      setCopiedText(null)
      console.warn("Copy failed")
    }
    return ok
  }, [])

  return [copiedText, copy]
}
