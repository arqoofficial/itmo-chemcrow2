import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import { cn } from "@/lib/utils"

interface MarkdownContentProps {
  content: string
  className?: string
}

export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div className={cn("prose-chat", className)}>
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
        ul: ({ children }) => (
          <ul className="mb-2 ml-4 list-disc last:mb-0">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="mb-2 ml-4 list-decimal last:mb-0">{children}</ol>
        ),
        li: ({ children }) => <li className="mb-0.5">{children}</li>,
        h1: ({ children }) => (
          <h1 className="mb-2 text-lg font-bold">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-2 text-base font-bold">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-1 text-sm font-semibold">{children}</h3>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold">{children}</strong>
        ),
        code: ({ className: codeClassName, children, ...props }) => {
          const isInline = !codeClassName
          if (isInline) {
            return (
              <code
                className="rounded bg-black/10 px-1 py-0.5 text-[0.85em] dark:bg-white/10"
                {...props}
              >
                {children}
              </code>
            )
          }
          return (
            <code className={cn("text-[0.85em]", codeClassName)} {...props}>
              {children}
            </code>
          )
        },
        pre: ({ children }) => (
          <pre className="my-2 overflow-x-auto rounded-lg bg-black/5 p-3 text-xs dark:bg-white/5">
            {children}
          </pre>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-2 border-l-2 border-muted-foreground/30 pl-3 italic">
            {children}
          </blockquote>
        ),
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto">
            <table className="min-w-full text-xs">{children}</table>
          </div>
        ),
        th: ({ children }) => (
          <th className="border-b px-2 py-1 text-left font-semibold">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border-b px-2 py-1">{children}</td>
        ),
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline hover:no-underline"
          >
            {children}
          </a>
        ),
        hr: () => <hr className="my-3 border-muted-foreground/20" />,
      }}
    >
      {content}
    </ReactMarkdown>
    </div>
  )
}
