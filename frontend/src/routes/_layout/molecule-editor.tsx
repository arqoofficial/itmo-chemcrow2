import { createFileRoute } from "@tanstack/react-router"
import { FlaskConical } from "lucide-react"
import { lazy, Suspense } from "react"

const KetcherEditor = lazy(
  () => import("@/components/MoleculeEditor/KetcherEditor"),
)

export const Route = createFileRoute("/_layout/molecule-editor")({
  component: MoleculeEditor,
  head: () => ({
    meta: [{ title: "Molecule Editor - ChemCrow2" }],
  }),
})

function MoleculeEditor() {
  return (
    <div
      className="flex flex-col overflow-hidden"
      style={{ height: "calc(100dvh - 185px)" }}
    >
      <div className="shrink-0 pb-4">
        <h1 className="text-2xl font-bold tracking-tight">Molecule Editor</h1>
        <p className="text-muted-foreground">
          Draw and edit chemical structures using Ketcher
        </p>
      </div>
      <div className="flex-1 min-h-0 rounded-lg border overflow-hidden">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-full text-muted-foreground gap-2">
              <FlaskConical className="h-5 w-5 animate-pulse" />
              <span>Loading molecule editor...</span>
            </div>
          }
        >
          <KetcherEditor />
        </Suspense>
      </div>
    </div>
  )
}
