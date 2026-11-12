'use client'

import { useState } from 'react'
import { Button, Sheet, inputClass } from '@/components/ui'
import type { FeedbackKind } from '@/lib/format'

// What will happen with the text, so the owner knows before sending.
const NOTE: Record<FeedbackKind, string> = {
  follow_up: 'Изменение уже в stage — создам новую задачу-доработку, связанную с этой.',
  same_pr: 'Агент продолжит в той же сессии и обновит этот же PR.',
  description: 'Допишем к задаче: агент учтёт, когда возьмёт её в работу.',
}

export const feedbackTitle = (kind: FeedbackKind | null) => (kind === 'follow_up' ? 'Доработать' : 'Правки')

export function FeedbackSheet({
  open,
  onClose,
  kind,
  onSubmit,
  busy,
}: {
  open: boolean
  onClose: () => void
  /** Null: the task stopped taking feedback while the sheet was open. */
  kind: FeedbackKind | null
  onSubmit: (text: string) => void
  busy: boolean
}) {
  const [text, setText] = useState('')
  return (
    <Sheet open={open} onClose={onClose} title={feedbackTitle(kind)}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (text.trim()) onSubmit(text.trim())
        }}
      >
        {kind && <p className="text-sm text-muted">{NOTE[kind]}</p>}
        <textarea
          autoFocus
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={inputClass}
          placeholder="Сделай кнопку заметнее и добавь подтверждение удаления"
        />
        <Button type="submit" variant="primary" className="w-full" disabled={busy || !text.trim()}>
          Отправить
        </Button>
      </form>
    </Sheet>
  )
}
