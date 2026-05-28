import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function ChatMarkdown({
  content,
  className = "",
}: {
  content: string;
  className?: string;
}) {
  return (
    <div
      className={[
        "kn-md prose-paper max-w-none overflow-hidden py-0",
        "[&_ol:first-child]:mt-0 [&_ol:last-child]:mb-0",
        "[&_p:first-child]:mt-0 [&_p:last-child]:mb-0",
        "[&_ul:first-child]:mt-0 [&_ul:last-child]:mb-0",
        className,
      ].join(" ")}
      style={{
        color: "var(--ink)",
        fontSize: "14px",
        lineHeight: 1.65,
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
