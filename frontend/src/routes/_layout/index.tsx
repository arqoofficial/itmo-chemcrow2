import { createFileRoute } from "@tanstack/react-router"
import { Badge } from "@/components/ui/badge"
import useAuth from "@/hooks/useAuth"
import chemcrowImg from "/assets/images/chemcrow2_3.jpg"
import itmoHackathon from "/assets/images/itmo-hackathon.png"

export const Route = createFileRoute("/_layout/")({
  component: Dashboard,
  head: () => ({
    meta: [
      {
        title: "Dashboard - ChemCrow2",
      },
    ],
  }),
})

const technologies = [
  { name: "FastAPI", category: "backend" },
  { name: "Python", category: "backend" },
  { name: "LangChain", category: "ai" },
  { name: "OpenAI GPT-4", category: "ai" },
  { name: "RDKit", category: "chem" },
  { name: "Ketcher", category: "chem" },
  { name: "React 19", category: "frontend" },
  { name: "TypeScript", category: "frontend" },
  { name: "TanStack Router", category: "frontend" },
  { name: "PostgreSQL", category: "backend" },
  { name: "Docker", category: "infra" },
  { name: "Cursor", category: "ai" },
  { name: "Tailwind CSS", category: "frontend" },
]

const categoryColors: Record<string, string> = {
  backend:
    "bg-blue-500/10 text-blue-400 border-blue-500/20 hover:bg-blue-500/20",
  ai: "bg-purple-500/10 text-purple-400 border-purple-500/20 hover:bg-purple-500/20",
  chem: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20",
  frontend:
    "bg-amber-500/10 text-amber-400 border-amber-500/20 hover:bg-amber-500/20",
  infra: "bg-rose-500/10 text-rose-400 border-rose-500/20 hover:bg-rose-500/20",
}

function Dashboard() {
  const { user: currentUser } = useAuth()

  return (
    <div className="space-y-8 pb-8">
      {/* Greeting */}
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold truncate max-w-sm">
          Привет, {currentUser?.full_name || currentUser?.email} 👋
        </h1>
        <p className="text-muted-foreground text-sm">
          Рады видеть тебя снова в ChemCrow2
        </p>
      </div>

      {/* Hero section */}
      <div className="relative overflow-hidden rounded-2xl border border-emerald-200/50 bg-gradient-to-br from-white to-emerald-100 dark:from-zinc-900 dark:to-emerald-950/50 dark:border-emerald-800/30 p-8 md:p-10">
        {/* Decorative glow */}
        <div className="pointer-events-none absolute -bottom-12 -right-12 w-64 h-64 bg-emerald-300/20 dark:bg-emerald-500/5 rounded-full blur-3xl" />

        <div className="relative z-10 space-y-6 max-w-3xl">
          {/* Label */}
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/30 bg-white text-emerald-700 px-3 py-1 text-xs font-semibold shadow-sm">
              <span className="relative flex size-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-75" />
                <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
              </span>
              ITMO Hackathon 2026
            </span>
          </div>

          {/* Title */}
          <div className="space-y-3">
            <h2 className="text-4xl font-bold tracking-tight">
              Chem<span className="text-emerald-400">Crow</span>
              <span className="text-muted-foreground">2</span>
            </h2>
            <p className="text-lg leading-relaxed text-muted-foreground">
              Мы — команда хакатона{" "}
              <span className="font-semibold text-foreground">ITMO</span>,
              создавшая{" "}
              <span className="font-semibold text-emerald-400">ChemCrow2</span>{" "}
              — интеллектуальный агентный ассистент для химиков нового
              поколения. Приложение помогает специалистам в лабораторной работе:
              от поиска информации о соединениях до прогнозирования свойств
              молекул и планирования синтеза.
            </p>
          </div>

          {/* Description */}
          <div className="rounded-xl border border-emerald-200/70 bg-emerald-50/60 dark:border-white/5 dark:bg-white/5 p-4 space-y-2">
            <p className="text-sm font-medium text-foreground">
              Умная агентная система нового поколения
            </p>
            <p className="text-sm text-muted-foreground leading-relaxed">
              ChemCrow2 использует наиболее инновационные подходы в области
              применения искусственного интеллекта в химии. Мультиагентная
              архитектура на базе LLM позволяет выполнять сложные задачи:
              анализировать молекулярные структуры, предсказывать реакции,
              находить релевантные публикации и генерировать протоколы
              экспериментов в интерактивном диалоге.
            </p>
          </div>

          {/* Technologies */}
          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
              Ключевые технологии
            </p>
            <div className="flex flex-wrap gap-2">
              {technologies.map(({ name, category }) => (
                <Badge
                  key={name}
                  variant="outline"
                  className={`cursor-default transition-colors ${categoryColors[category]}`}
                >
                  {name}
                </Badge>
              ))}
            </div>
            <div className="flex flex-wrap gap-4 pt-1">
              {(["backend", "ai", "chem", "frontend", "infra"] as const).map(
                (cat) => (
                  <span
                    key={cat}
                    className="flex items-center gap-1.5 text-xs text-muted-foreground"
                  >
                    <span
                      className={`inline-block size-2 rounded-full ${categoryColors[cat].split(" ")[0].replace("/10", "/60")}`}
                    />
                    {
                      {
                        backend: "Backend",
                        ai: "AI / LLM",
                        chem: "Химия",
                        frontend: "Frontend",
                        infra: "Инфраструктура",
                      }[cat]
                    }
                  </span>
                ),
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Images section — flex distributes width in 1722:670 ratio keeping both images the same height */}
      <div className="flex items-center gap-4">
        <div className="flex-[1722] min-w-0 overflow-hidden rounded-2xl border shadow-md aspect-[1722/670]">
          <img
            src={itmoHackathon}
            alt="ITMO Hackathon"
            className="w-full h-full object-cover block"
          />
        </div>

        <div className="flex-shrink-0 px-1">
          <span className="text-3xl font-bold text-muted-foreground select-none">
            +
          </span>
        </div>

        <div className="flex-[670] min-w-0 overflow-hidden rounded-2xl border shadow-md aspect-square">
          <img
            src={chemcrowImg}
            alt="ChemCrow2 Team"
            className="w-full h-full object-cover block"
          />
        </div>
      </div>
    </div>
  )
}
