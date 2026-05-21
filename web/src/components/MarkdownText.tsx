import React from "react";

/**
 * Lightweight inline markdown renderer.
 * Handles: **bold**, *italic*, `code`, - bullet lists, | tables |, and line breaks.
 * No external dependencies.
 */
export function MarkdownText({ text, style }: { text: string; style?: React.CSSProperties }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let bulletBuffer: string[] = [];
  let tableBuffer: string[] = [];
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

  function flushTable() {
    if (tableBuffer.length > 0) {
      elements.push(<MarkdownTable key={key++} rows={tableBuffer} />);
      tableBuffer = [];
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();

    // Table row: starts with |
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      flushBullets();
      tableBuffer.push(trimmed);
      continue;
    }

    // Flush any pending table before non-table content
    flushTable();

    // Bullet point
    if (trimmed.startsWith("- ")) {
      bulletBuffer.push(trimmed.slice(2));
      continue;
    }

    // Flush any pending bullets before non-bullet content
    flushBullets();

    // H4 heading (####) — render as a styled box/label
    if (trimmed.startsWith("#### ")) {
      const heading = trimmed.slice(5);
      elements.push(
        <div
          key={key++}
          style={{
            margin: "1rem 0 0.5rem 0",
            padding: "0.5rem 0.75rem",
            background: "rgba(212, 165, 116, 0.08)",
            border: "1px solid var(--color-accent, #d4a574)",
            borderRadius: "var(--radius-md, 8px)",
            fontWeight: 600,
            fontSize: "0.9375rem",
            color: "var(--color-text)",
          }}
        >
          <InlineMarkdown text={heading} />
        </div>
      );
      continue;
    }

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
  flushTable();

  return <div style={style}>{elements}</div>;
}

/**
 * Renders a markdown table from buffered pipe-delimited rows.
 * Detects the separator row (|---|---|) and splits header from body.
 */
function MarkdownTable({ rows }: { rows: string[] }) {
  function parseCells(row: string): string[] {
    return row
      .split("|")
      .slice(1, -1) // remove empty first/last from leading/trailing |
      .map((cell) => cell.trim());
  }

  function isSeparatorRow(row: string): boolean {
    return /^\|[\s\-:|]+\|$/.test(row);
  }

  // Find separator row index
  const sepIdx = rows.findIndex(isSeparatorRow);
  const headerRows = sepIdx > 0 ? rows.slice(0, sepIdx) : [];
  const bodyRows = sepIdx >= 0 ? rows.slice(sepIdx + 1) : rows;

  const tableStyle: React.CSSProperties = {
    width: "100%",
    borderCollapse: "collapse",
    margin: "0.75rem 0",
    fontSize: "0.9em",
    lineHeight: 1.5,
  };

  const thStyle: React.CSSProperties = {
    padding: "0.5rem 0.75rem",
    borderBottom: "2px solid var(--color-border, #ddd)",
    textAlign: "left",
    fontWeight: 600,
    background: "var(--color-bg-secondary, rgba(0,0,0,0.03))",
  };

  const tdStyle: React.CSSProperties = {
    padding: "0.5rem 0.75rem",
    borderBottom: "1px solid var(--color-border, #eee)",
    textAlign: "left",
  };

  return (
    <div style={{ overflowX: "auto", margin: "0.75rem 0" }}>
      <table style={tableStyle}>
        {headerRows.length > 0 && (
          <thead>
            {headerRows.map((row, ri) => (
              <tr key={ri}>
                {parseCells(row).map((cell, ci) => (
                  <th key={ci} style={thStyle}>
                    <InlineMarkdown text={cell} />
                  </th>
                ))}
              </tr>
            ))}
          </thead>
        )}
        <tbody>
          {bodyRows.map((row, ri) => (
            <tr key={ri}>
              {parseCells(row).map((cell, ci) => (
                <td key={ci} style={tdStyle}>
                  <InlineMarkdown text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
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
