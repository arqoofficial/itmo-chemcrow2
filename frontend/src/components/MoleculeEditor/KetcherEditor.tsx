import { Editor } from "ketcher-react"
import "ketcher-react/dist/index.css"
import { StandaloneStructServiceProvider } from "ketcher-standalone"

const structServiceProvider = new StandaloneStructServiceProvider()

export default function KetcherEditor() {
  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <Editor
        staticResourcesUrl=""
        structServiceProvider={structServiceProvider}
        errorHandler={(message) => console.error("Ketcher error:", message)}
      />
    </div>
  )
}
