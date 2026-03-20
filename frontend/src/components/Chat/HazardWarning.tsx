import { AlertTriangle, X } from "lucide-react"
import { useState } from "react"

import type { HazardChemical } from "@/client/chatTypes"

const CATEGORY_LABELS: Record<string, string> = {
  ACUTELY_TOXIC: "Остро токсично",
  CARCINOGEN: "Канцероген",
  FLAMMABLE: "Огнеопасно",
  NEUROTOXIN: "Нейротоксин",
  CORROSIVE: "Едкое",
  EXPLOSIVE: "Взрывоопасно",
  CHEMICAL_WEAPON: "Хим. оружие",
  PRECURSOR_CONTROLLED: "Прекурсор",
  ENVIRONMENTALLY_HAZARDOUS: "Эко-опасно",
}

const PKKN_LABELS: Record<string, string> = {
  potent: "ПККН Список №1 (сильнодействующие)",
  poisonous: "ПККН Список №2 (ядовитые)",
}

interface HazardWarningProps {
  chemicals: HazardChemical[]
}

export function HazardWarning({ chemicals }: HazardWarningProps) {
  const [open, setOpen] = useState(false)

  if (chemicals.length === 0) return null

  const hasCritical = chemicals.some((c) => c.severity === "critical")

  return (
    <div className="absolute bottom-[72px] right-4 z-50">
      {/* Tooltip panel */}
      {open && (
        <div className="absolute bottom-14 right-0 w-80 rounded-xl border bg-popover shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between rounded-t-xl border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <AlertTriangle
                className={`h-4 w-4 ${hasCritical ? "text-red-500" : "text-amber-500"}`}
              />
              <span className="text-sm font-semibold">
                Опасные вещества&nbsp;
                <span className="text-muted-foreground">({chemicals.length})</span>
              </span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="rounded p-1 hover:bg-muted"
              aria-label="Закрыть"
            >
              <X className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
          </div>

          {/* Chemical list */}
          <div className="max-h-[400px] overflow-y-auto p-3 space-y-2">
            {chemicals.map((chem) => {
              const isCritical = chem.severity === "critical"
              return (
                <div
                  key={chem.id}
                  className={`rounded-lg border p-3 text-xs ${
                    isCritical
                      ? "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-950/40"
                      : "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40"
                  }`}
                >
                  {/* Name */}
                  <div className="font-semibold text-foreground text-sm">
                    {chem.names[0]}
                  </div>
                  {chem.names[1] && chem.names[1] !== chem.names[0] && (
                    <div className="text-muted-foreground mt-0.5">
                      {chem.names[1]}
                    </div>
                  )}

                  {/* Meta: CAS, PKKN list */}
                  <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
                    {chem.cas && <span>CAS: {chem.cas}</span>}
                    {chem.pkkn_list && (
                      <span>{PKKN_LABELS[chem.pkkn_list] ?? chem.pkkn_list}</span>
                    )}
                  </div>

                  {/* Hazard category badges */}
                  {chem.hazard_categories.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {chem.hazard_categories.map((cat) => (
                        <span
                          key={cat}
                          className={`rounded px-1.5 py-0.5 font-medium ${
                            isCritical
                              ? "bg-red-100 text-red-700 dark:bg-red-900/60 dark:text-red-300"
                              : "bg-amber-100 text-amber-700 dark:bg-amber-900/60 dark:text-amber-300"
                          }`}
                        >
                          {CATEGORY_LABELS[cat] ?? cat}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Safety warnings */}
                  {chem.safety_warnings.length > 0 && (
                    <ul className="mt-2 space-y-0.5 text-muted-foreground">
                      {chem.safety_warnings.slice(0, 4).map((w, i) => (
                        <li key={i} className="flex gap-1.5">
                          <span className="shrink-0 mt-px">•</span>
                          <span>{w}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Floating action button */}
      <button
        onClick={() => setOpen((v) => !v)}
        title="Обнаружены опасные вещества — нажмите для подробностей"
        className={`relative flex h-11 w-11 items-center justify-center rounded-full shadow-lg transition-all hover:scale-110 focus:outline-none focus:ring-2 focus:ring-offset-2 ${
          hasCritical
            ? "animate-pulse bg-red-500 hover:bg-red-600 focus:ring-red-400"
            : "bg-amber-500 hover:bg-amber-600 focus:ring-amber-400"
        }`}
      >
        <AlertTriangle className="h-5 w-5 text-white" />
        {chemicals.length > 1 && (
          <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-white text-[10px] font-bold leading-none text-red-600 shadow">
            {chemicals.length}
          </span>
        )}
      </button>
    </div>
  )
}
