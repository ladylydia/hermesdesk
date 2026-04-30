import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark.css";

type Props = {
  text: string;
  className?: string;
};

export function ChatMarkdown({ text, className = "" }: Props) {
  return (
    <div
      className={`chat-md text-sm leading-[1.6] text-zinc-800 dark:text-zinc-200 ${className}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-sky-600 dark:text-sky-400 underline underline-offset-2"
            >
              {children}
            </a>
          ),
          p: ({ children }) => <p className="mb-2 last:mb-0 whitespace-pre-wrap">{children}</p>,
          ul: ({ children }) => (
            <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>
          ),
          h1: ({ children }) => (
            <h1 className="text-base font-semibold mt-2 mb-1">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm font-semibold mt-2 mb-1">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-medium mt-2 mb-0.5">{children}</h3>
          ),
          pre: ({ children }) => {
            const codeEl = React.Children.toArray(children).find(
              (c) => React.isValidElement(c) && c.type === "code"
            ) as React.ReactElement<{ className?: string }> | undefined;
            const lang = (codeEl?.props?.className ?? "").replace("language-", "");
            return (
              <div className="my-3 rounded-xl overflow-hidden border border-zinc-700/50 shadow-sm">
                {lang && (
                  <div className="flex items-center justify-between px-3 py-1.5 bg-zinc-800 text-zinc-400 text-[11px] font-mono uppercase tracking-wide">
                    <span>{lang}</span>
                  </div>
                )}
                <pre className="p-4 overflow-x-auto bg-zinc-900 font-mono text-zinc-100 text-xs leading-relaxed">
                  {children}
                </pre>
              </div>
            );
          },
          code: ({ className, children, ...rest }) => {
            const isBlock = (className ?? "").includes("language-");
            if (isBlock) {
              return (
                <code className={className} {...rest}>
                  {children}
                </code>
              );
            }
            return (
              <code className="hd-inline-code" {...rest}>
                {children}
              </code>
            );
          },
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-zinc-300 dark:border-zinc-600 pl-3 my-2 text-zinc-600 dark:text-zinc-400">
              {children}
            </blockquote>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
