import { Link } from "@tanstack/react-router"

import { useTheme } from "@/components/theme-provider"
import { cn } from "@/lib/utils"
import chemIcon from "/assets/images/chemcrow2_3.jpg"
import logo from "/assets/images/fastapi-logo.svg"
import logoLight from "/assets/images/fastapi-logo-light.svg"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === "dark"

  const fullLogo = isDark ? logoLight : logo

  const content =
    variant === "responsive" ? (
      <>
        <img
          src={fullLogo}
          alt="ChemCrow2"
          className={cn(
            "h-6 w-auto group-data-[collapsible=icon]:hidden",
            className,
          )}
        />
        <img
          src={chemIcon}
          alt="ChemCrow2"
          className={cn(
            "size-6 rounded-full object-cover hidden group-data-[collapsible=icon]:block",
            className,
          )}
        />
      </>
    ) : (
      <img
        src={variant === "full" ? fullLogo : chemIcon}
        alt="ChemCrow2"
        className={cn(
          variant === "full" ? "h-6 w-auto" : "size-6 rounded-full object-cover",
          className,
        )}
      />
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
