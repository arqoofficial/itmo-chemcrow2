import hljs from "highlight.js"
import { memo, useMemo } from "react"
import ReactMarkdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import "highlight.js/styles/github-dark-dimmed.css"

import { cn } from "@/lib/utils"

interface MarkdownContentProps {
  content: string
  className?: string
}

const remarkPlugins = [remarkGfm]

const mdComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => (
    <ul className="mb-2 ml-4 list-disc last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 ml-4 list-decimal last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  h1: ({ children }) => <h1 className="mb-2 text-lg font-bold">{children}</h1>,
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

    // ReactMarkdown передаёт язык в className вида `language-js`.
    // highlight.js вернёт HTML со span'ами и CSS-классами для темы.
    const languageMatch = codeClassName?.match(/language-([A-Za-z0-9_-]+)/)
    const language = languageMatch?.[1]
    const codeText = String(children ?? "")

    const highlighted =
      language && hljs.getLanguage(language)
        ? hljs.highlight(codeText, { language, ignoreIllegals: true }).value
        : hljs.highlightAuto(codeText).value

    return (
      <code
        className={cn("hljs text-[0.85em]", codeClassName)}
        // Biome не может статически доказать, что highlight.js экранирует исходный код.
        // Мы используем результат highlight.js только для подсветки fenced-блоков.
        // biome-ignore lint/security/noDangerouslySetInnerHtml: highlight.js highlights escaped code
        dangerouslySetInnerHTML={{ __html: highlighted }}
        {...props}
      />
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
    <th className="border-b px-2 py-1 text-left font-semibold">{children}</th>
  ),
  td: ({ children }) => <td className="border-b px-2 py-1">{children}</td>,
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
  img: ({ src, alt }) => (
    <img
      src={src}
      alt={alt ?? ""}
      className="mt-4 mb-2 max-w-full rounded-lg"
      style={{ maxHeight: "400px" }}
    />
  ),
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
  className,
}: MarkdownContentProps) {
  const wrapperClassName = useMemo(
    () => cn("prose-chat", className),
    [className],
  )

  return (
    <div className={wrapperClassName}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        components={mdComponents}
        urlTransform={(url) => (url.startsWith("javascript:") ? "" : url)}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
})
