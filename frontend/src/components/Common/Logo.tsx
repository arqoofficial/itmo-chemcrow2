import { Link } from "@tanstack/react-router"

import { cn } from "@/lib/utils"
import chemIcon from "/assets/images/chemcrow2_3.jpg"
import chemLogo from "/assets/images/chemcrow2-logo.png"

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
  const content =
    variant === "responsive" ? (
      <>
        <img
          src={chemLogo}
          alt="ChemCrow2"
          className={cn(
            "h-8 w-auto rounded-lg group-data-[collapsible=icon]:hidden",
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
        src={variant === "full" ? chemLogo : chemIcon}
        alt="ChemCrow2"
        className={cn(
          variant === "full"
            ? "h-6 w-auto"
            : "size-6 rounded-full object-cover",
          className,
        )}
      />
    )

  if (!asLink) {
    return content
  }

  return <Link to="/">{content}</Link>
}
