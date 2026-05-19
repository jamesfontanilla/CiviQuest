import React from "react";

/**
 * Lightweight inline markdown renderer.
 * Handles: **bold**, *italic*, `code`, - bullet lists, and line breaks.
 * No external dependencies.
 */
export function MarkdownText({ text, style }: { text: string; style?: React.CSSProperties }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let bulletBuffer: string[] = [];
  let key = 0;

  function flushBullets() {
    if (bulletBuffer.length > 0) {
      elements.push(
        <ul key={key++} style={{ margin: "0.5rem 0", paddingLeft: "1.5rem" }}>
          {bulletBuffer.map((b, i) => (
            <li key={i} style={{ marginBottom: "0.375rem", lineHeight: 1.6 }}>
              <InlineMarkdown text={b} />
            </li>
          ))}
        </ul>
      );
      bulletBuffer = [];
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();

    // Bullet point
    if (trimmed.startsWith("- ")) {
      bulletBuffer.push(trimmed.slice(2));
      continue;
    }

    // Flush any pending bullets before non-bullet content
    flushBullets();

    // Empty line = paragraph break
    if (trimmed === "") {
      elements.push(<br key={key++} />);
      continue;
    }

    // Regular paragraph
    elements.push(
      <p key={key++} style={{ margin: "0 0 0.5rem 0", lineHeight: 1.7 }}>
        <InlineMarkdown text={trimmed} />
      </p>
    );
  }

  flushBullets();

  return <div style={style}>{elements}</div>;
}

/**
 * Renders inline markdown: **bold**, *italic*, `code`
 */
function InlineMarkdown({ text }: { text: string }) {
  // Split by markdown patterns and render with appropriate styling
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    // Bold: **text**
    const boldMatch = remaining.match(/^(.*?)\*\*(.+?)\*\*(.*)/s);
    if (boldMatch) {
      if (boldMatch[1]) parts.push(<span key={key++}>{boldMatch[1]}</span>);
      parts.push(<strong key={key++}>{boldMatch[2]}</strong>);
      remaining = boldMatch[3];
      continue;
    }

    // Italic: *text*
    const italicMatch = remaining.match(/^(.*?)\*(.+?)\*(.*)/s);
    if (italicMatch) {
      if (italicMatch[1]) parts.push(<span key={key++}>{italicMatch[1]}</span>);
      parts.push(<em key={key++}>{italicMatch[2]}</em>);
      remaining = italicMatch[3];
      continue;
    }

    // Inline code: `text`
    const codeMatch = remaining.match(/^(.*?)`(.+?)`(.*)/s);
    if (codeMatch) {
      if (codeMatch[1]) parts.push(<span key={key++}>{codeMatch[1]}</span>);
      parts.push(
        <code key={key++} style={{ background: "var(--color-bg-secondary, #f0f0f0)", padding: "0.125rem 0.375rem", borderRadius: "3px", fontSize: "0.875em" }}>
          {codeMatch[2]}
        </code>
      );
      remaining = codeMatch[3];
      continue;
    }

    // No more patterns — output the rest as plain text
    parts.push(<span key={key++}>{remaining}</span>);
    break;
  }

  return <>{parts}</>;
}
