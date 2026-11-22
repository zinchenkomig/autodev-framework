'use client'

import { EFFORTS, MODELS } from '@/lib/format'
import { Field, inputClass } from './ui'

/** Model and effort selects; '' takes them from the level above (the project, or the server's default). */
export function ClaudePicker({
  model,
  effort,
  onChange,
  inherit,
}: {
  model: string
  effort: string
  onChange: (pick: { model: string; effort: string }) => void
  /** What '' means: "Как в проекте (Opus)", "По умолчанию" */
  inherit: { model: string; effort: string }
}) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Модель">
        <Select value={model} options={MODELS} inherit={inherit.model} onChange={(v) => onChange({ model: v, effort })} />
      </Field>
      <Field label="Усилие">
        <Select value={effort} options={EFFORTS} inherit={inherit.effort} onChange={(v) => onChange({ model, effort: v })} />
      </Field>
    </div>
  )
}

function Select({
  value,
  options,
  inherit,
  onChange,
}: {
  value: string
  options: Record<string, string>
  inherit: string
  onChange: (value: string) => void
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass}>
      <option value="">{inherit}</option>
      {Object.entries(options).map(([id, name]) => (
        <option key={id} value={id}>
          {name}
        </option>
      ))}
      {/* a name typed before there was a list */}
      {value && !(value in options) && <option value={value}>{value}</option>}
    </select>
  )
}

/** "Как в проекте (Opus)" — what an empty pick on a task falls back to. */
export function inheritLabel(base: string, value: string | null | undefined, names: Record<string, string>): string {
  return value ? `${base} (${names[value] ?? value})` : base
}
