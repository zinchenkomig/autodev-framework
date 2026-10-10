'use client'

import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { ProjectInput, Repo } from '@/lib/api'
import { Button, ErrorNote, Field, inputClass } from './ui'

export const EMPTY_PROJECT: ProjectInput = {
  id: '',
  name: '',
  repos: [{ name: '', role: 'app' }],
  base_branch: 'stage',
  prod_branch: 'main',
  stage_url: null,
  smoke_paths: [],
  instructions: null,
  model: null,
  max_parallel: 1,
  enabled: true,
}

const orNull = (v: string) => (v.trim() ? v.trim() : null)

export function ProjectForm({
  initial,
  isNew,
  onSubmit,
}: {
  initial: ProjectInput
  isNew: boolean
  onSubmit: (p: ProjectInput) => Promise<void>
}) {
  const [p, setP] = useState<ProjectInput>(initial)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) => setP((prev) => ({ ...prev, [key]: value }))
  const setRepo = (i: number, patch: Partial<Repo>) =>
    set(
      'repos',
      p.repos.map((r, j) => (j === i ? { ...r, ...patch } : r)),
    )

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit({
        ...p,
        repos: p.repos
          .filter((r) => r.name.trim())
          .map((r) => ({
            name: r.name.trim(),
            role: r.role.trim() || 'app',
            version_url: orNull(r.version_url ?? ''),
            setup: orNull(r.setup ?? ''),
          })),
      })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Название">
          <input required value={p.name} onChange={(e) => set('name', e.target.value)} className={inputClass} />
        </Field>
        <Field label="Идентификатор" hint="латиница, цифры, дефис">
          <input
            required
            disabled={!isNew}
            pattern="[a-z0-9][a-z0-9-]*"
            value={p.id}
            onChange={(e) => set('id', e.target.value.toLowerCase())}
            className={inputClass}
          />
        </Field>
      </div>

      <div className="space-y-3">
        <div className="text-sm font-medium">Репозитории</div>
        {p.repos.map((r, i) => (
          <div key={i} className="space-y-3 rounded-2xl border border-line p-3">
            <div className="flex gap-2">
              <input
                required
                placeholder="owner/repo"
                value={r.name}
                onChange={(e) => setRepo(i, { name: e.target.value })}
                className={inputClass}
              />
              <input
                placeholder="роль"
                value={r.role}
                onChange={(e) => setRepo(i, { role: e.target.value })}
                className={`${inputClass} max-w-[7.5rem]`}
              />
              {p.repos.length > 1 && (
                <Button type="button" variant="ghost" onClick={() => set('repos', p.repos.filter((_, j) => j !== i))} aria-label="Убрать">
                  <Trash2 size={16} />
                </Button>
              )}
            </div>
            <Field label="URL версии на stage" hint="Отдаёт SHA задеплоенного коммита. Без него ждём успешных workflow на stage.">
              <input
                placeholder="https://stage.example.com/api/version"
                value={r.version_url ?? ''}
                onChange={(e) => setRepo(i, { version_url: e.target.value })}
                className={inputClass}
              />
            </Field>
            <Field label="Setup-скрипт" hint="Выполняется в свежем чекауте до старта агента (кодген и т.п.).">
              <textarea
                rows={2}
                value={r.setup ?? ''}
                onChange={(e) => setRepo(i, { setup: e.target.value })}
                className={`${inputClass} font-mono text-sm`}
              />
            </Field>
          </div>
        ))}
        <Button type="button" size="sm" onClick={() => set('repos', [...p.repos, { name: '', role: 'app' }])}>
          <Plus size={15} /> Репозиторий
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="URL stage">
          <input
            type="url"
            placeholder="https://stage.example.com"
            value={p.stage_url ?? ''}
            onChange={(e) => set('stage_url', orNull(e.target.value))}
            className={inputClass}
          />
        </Field>
        <Field label="Модель Claude" hint="пусто — по умолчанию">
          <input
            placeholder="opus / sonnet"
            value={p.model ?? ''}
            onChange={(e) => set('model', orNull(e.target.value))}
            className={inputClass}
          />
        </Field>
        <Field label="Ветка stage">
          <input required value={p.base_branch} onChange={(e) => set('base_branch', e.target.value)} className={inputClass} />
        </Field>
        <Field label="Ветка прода">
          <input required value={p.prod_branch} onChange={(e) => set('prod_branch', e.target.value)} className={inputClass} />
        </Field>
        <Field label="Задач параллельно">
          <input
            type="number"
            min={1}
            max={10}
            value={p.max_parallel}
            onChange={(e) => set('max_parallel', Number(e.target.value) || 1)}
            className={inputClass}
          />
        </Field>
        <label className="flex items-center gap-3 self-end pb-3">
          <input type="checkbox" checked={p.enabled} onChange={(e) => set('enabled', e.target.checked)} className="h-5 w-5 accent-[var(--accent)]" />
          <span className="text-sm">Агенты работают над проектом</span>
        </label>
      </div>

      <Field label="Инструкции для агента" hint="Дополнение к CLAUDE.md репозитория.">
        <textarea
          rows={4}
          value={p.instructions ?? ''}
          onChange={(e) => set('instructions', orNull(e.target.value))}
          className={inputClass}
        />
      </Field>

      <ErrorNote error={error} />
      <Button type="submit" variant="primary" disabled={busy} className="w-full sm:w-auto">
        {busy ? 'Сохраняю…' : isNew ? 'Создать проект' : 'Сохранить'}
      </Button>
    </form>
  )
}
