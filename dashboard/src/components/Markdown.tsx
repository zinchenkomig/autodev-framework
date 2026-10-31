import { Fragment } from 'react'
import { cx } from '@/lib/format'

const LIST_ITEM = /^\s*([-*•]|\d+[.)])\s+/
const HEADING = /^\s*#{1,6}\s+/

type Block =
  | { kind: 'p'; lines: string[] }
  | { kind: 'h'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }

/** Split text into paragraphs, headings and lists — a list may follow its lead-in line without a blank line. */
function parse(text: string): Block[] {
  const blocks: Block[] = []
  let last: Block | undefined
  for (const line of text.trim().split('\n')) {
    if (!line.trim()) {
      last = undefined
    } else if (HEADING.test(line)) {
      blocks.push({ kind: 'h', text: line.replace(HEADING, '') })
      last = undefined
    } else if (LIST_ITEM.test(line)) {
      const item = line.replace(LIST_ITEM, '')
      if (last?.kind === 'list') last.items.push(item)
      else blocks.push((last = { kind: 'list', ordered: /^\s*\d/.test(line), items: [item] }))
    } else if (last?.kind === 'list' && /^\s+/.test(line)) {
      last.items[last.items.length - 1] += ' ' + line.trim()
    } else if (last?.kind === 'p') {
      last.lines.push(line)
    } else {
      blocks.push((last = { kind: 'p', lines: [line] }))
    }
  }
  return blocks
}

/** The light Markdown agents write: paragraphs, headings, lists, **bold** and `code`. */
export function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={cx('space-y-2 break-words', className)}>
      {parse(text).map((b, i) => {
        if (b.kind === 'h')
          return (
            <div key={i} className="pt-1 font-semibold">
              <Inline text={b.text} />
            </div>
          )
        if (b.kind === 'list') {
          const List = b.ordered ? 'ol' : 'ul'
          return (
            <List key={i} className={cx('space-y-1 pl-5', b.ordered ? 'list-decimal' : 'list-disc')}>
              {b.items.map((item, j) => (
                <li key={j}>
                  <Inline text={item} />
                </li>
              ))}
            </List>
          )
        }
        return (
          <p key={i} className="whitespace-pre-wrap">
            <Inline text={b.lines.join('\n')} />
          </p>
        )
      })}
    </div>
  )
}

export function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
          <strong key={i} className="font-semibold">
            {part.slice(2, -2)}
          </strong>
        ) : part.startsWith('`') && part.endsWith('`') && part.length > 2 ? (
          <code key={i} className="rounded bg-bg px-1 py-0.5 font-mono text-[0.9em]">
            {part.slice(1, -1)}
          </code>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}
