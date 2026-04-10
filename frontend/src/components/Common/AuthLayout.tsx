import { Appearance } from "@/components/Common/Appearance"
import chemcrowImg from "/assets/images/chemcrow2_3.jpg"
import itmoHackathon from "/assets/images/itmo-hackathon.png"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="bg-muted dark:bg-zinc-900 relative hidden lg:flex lg:items-center lg:justify-center px-12">
        <div className="flex items-center gap-4 w-full max-w-lg">
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
              alt="ChemCrow2"
              className="w-full h-full object-cover block"
            />
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-4 p-6 md:p-10">
        <div className="flex justify-end">
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-xs">{children}</div>
        </div>
        <Footer />
      </div>
    </div>
  )
}
