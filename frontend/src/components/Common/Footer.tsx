import { FaGithub } from "react-icons/fa"
import { ExternalLink } from "lucide-react"

const socialLinks = [
  {
    icon: FaGithub,
    href: "https://github.com/arqoofficial/itmo-fastapi-fullstack",
    label: "GitHub",
  },
]

export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t py-4 px-6">
      <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
        <p className="text-muted-foreground text-sm">
          ChemCrow2 — {currentYear}
        </p>

        <div className="flex items-center gap-5">
          <a
            href="https://www.prostospb.team/hackathon-26"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-emerald-400 transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            ITMO Hackathon 2026
          </a>

          {socialLinks.map(({ icon: Icon, href, label }) => (
            <a
              key={label}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={label}
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <Icon className="h-5 w-5" />
            </a>
          ))}
        </div>
      </div>
    </footer>
  )
}
