import { useCallback, useRef, useState } from "react"
import { Editor } from "ketcher-react"
import "ketcher-react/dist/index.css"
import { StandaloneStructServiceProvider } from "ketcher-standalone"

const structServiceProvider = new StandaloneStructServiceProvider()

export default function KetcherEditor() {
  const ketcherRef = useRef<any>(null)
  const [smiles, setSmiles] = useState("")

  const updateSmiles = useCallback(async () => {
    if (!ketcherRef.current) return
    try {
      const nextSmiles = await ketcherRef.current.getSmiles()
      setSmiles(nextSmiles)
    } catch (error) {
      console.error("Failed to get SMILES:", error)
    }
  }, [])

  const handleCopySmiles = useCallback(async () => {
    if (!smiles) return
    try {
      await navigator.clipboard.writeText(smiles)
    } catch (error) {
      console.error("Failed to copy SMILES:", error)
    }
  }, [smiles])

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
      <Editor
        staticResourcesUrl=""
        structServiceProvider={structServiceProvider}
        errorHandler={(message) => console.error("Ketcher error:", message)}
        onInit={(ketcher: any) => {
          ketcherRef.current = ketcher
          ketcher.editor.subscribe("change", () => {
            void updateSmiles()
          })
          void updateSmiles()
        }}
      />
      </div>
      <div
        style={{
          display: "flex",
          gap: 8,
          padding: 12,
          borderTop: "1px solid #e5e7eb",
          alignItems: "center",
        }}
      >
        <input
          value={smiles}
          readOnly
          placeholder="Current SMILES will appear here"
          style={{
            flex: 1,
            height: 36,
            padding: "0 12px",
            borderRadius: 8,
            border: "1px solid #d1d5db",
          }}
        />
        <button
          type="button"
          onClick={() => void handleCopySmiles()}
          disabled={!smiles}
          style={{
            height: 36,
            padding: "0 14px",
            borderRadius: 8,
            border: "1px solid var(--border)",
            background: smiles ? "var(--background)" : "var(--muted)",
            color: smiles ? "var(--foreground)" : "var(--muted-foreground)",
            cursor: smiles ? "pointer" : "not-allowed",
          }}
        >
          Copy
        </button>
      </div>
    </div>
  )
}
