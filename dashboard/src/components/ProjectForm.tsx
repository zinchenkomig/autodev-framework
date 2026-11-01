'use client'

import { useState } from 'react'
import type { NewRepo, ProjectInput, Repo } from '@/lib/api'
import { cx } from '@/lib/format'
import { Button, ErrorNote, Field, inputClass } from './ui'

export const EMPTY_PROJECT: ProjectInput = {
  id: '',
  name: '',
  repos: [{ name: '' }],
  base_branch: 'stage',
  prod_branch: 'main',
  stage_url: null,
  smoke_paths: [],
  instructions: null,
  pm: true,
  principles: null,
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
  onSubmit: (p: ProjectInput, newRepo?: NewRepo) => Promise<void>
}) {
  const [p, setP] = useState<ProjectInput>(initial)
  // A new project can start from an empty repo that the API creates on GitHub.
  const [newRepo, setNewRepo] = useState<NewRepo | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) => setP((prev) => ({ ...prev, [key]: value }))
  // One repo per project (several apps live in a monorepo); the API keeps it as a one-item list.
  const r = p.repos[0] ?? { name: '' }
  const setRepo = (patch: Partial<Repo>) => set('repos', [{ ...r, ...patch }])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await onSubmit(
        {
          ...p,
          repos: [{ name: r.name.trim(), version_url: orNull(r.version_url ?? ''), setup: orNull(r.setup ?? '') }],
        },
        newRepo ?? undefined,
      )
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

      <div className="space-y-3 rounded-2xl border border-line p-3">
        {isNew && (
          <div className="flex flex-wrap gap-2">
            {[
              { label: 'Подключить существующий', value: null },
              { label: 'Создать с нуля', value: { private: true, brief: '' } },
            ].map((mode) => (
              <button
                key={mode.label}
                type="button"
                onClick={() => setNewRepo(mode.value)}
                className={cx(
                  'rounded-full border px-3 py-1.5 text-sm',
                  (newRepo !== null) === (mode.value !== null)
                    ? 'border-accent bg-accent text-accent-fg'
                    : 'border-line bg-surface text-muted',
                )}
              >
                {mode.label}
              </button>
            ))}
          </div>
        )}
        <Field
          label="Репозиторий"
          hint={
            newRepo
              ? 'Создадим на GitHub с ветками stage и прода. Пусто или просто имя — в организации проектов: там stage и прод разворачиваются сами. Или owner/repo.'
              : 'Один на проект — несколько приложений держите в монорепо.'
          }
        >
          <input
            required={!newRepo}
            placeholder={newRepo ? p.id || 'имя репозитория' : 'owner/repo'}
            value={r.name}
            onChange={(e) => setRepo({ name: e.target.value })}
            className={inputClass}
          />
        </Field>
        {newRepo ? (
          <>
            <Field label="Что строим" hint="Станет первой задачей: агент выберет стек и заложит каркас — код, тесты, CI, CLAUDE.md.">
              <textarea
                rows={5}
                placeholder="Сервис заметок с тегами и поиском. Бэкенд на FastAPI, фронт на Next.js."
                value={newRepo.brief}
                onChange={(e) => setNewRepo({ ...newRepo, brief: e.target.value })}
                className={inputClass}
              />
            </Field>
            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={newRepo.private}
                onChange={(e) => setNewRepo({ ...newRepo, private: e.target.checked })}
                className="h-5 w-5 accent-[var(--accent)]"
              />
              <span className="text-sm">Приватный репозиторий</span>
            </label>
          </>
        ) : (
          <>
            <Field label="URL версии на stage" hint="Отдаёт SHA задеплоенного коммита. Без него ждём успешных workflow на stage.">
              <input
                placeholder="https://stage.example.com/api/version"
                value={r.version_url ?? ''}
                onChange={(e) => setRepo({ version_url: e.target.value })}
                className={inputClass}
              />
            </Field>
            <Field label="Setup-скрипт" hint="Выполняется в свежем чекауте до старта агента (кодген и т.п.).">
              <textarea
                rows={2}
                value={r.setup ?? ''}
                onChange={(e) => setRepo({ setup: e.target.value })}
                className={`${inputClass} font-mono text-sm`}
              />
            </Field>
          </>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="URL stage" hint={newRepo ? 'пусто — выдадим для проекта в организации' : undefined}>
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

      <label className="flex items-start gap-3">
        <input type="checkbox" checked={p.pm} onChange={(e) => set('pm', e.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--accent)]" />
        <span className="text-sm">
          PM продумывает задачи перед разработкой
          <span className="block text-muted">Значение по умолчанию для новых задач; у задачи можно выключить.</span>
        </span>
      </label>

      <Field
        label="Принципы продукта"
        hint="Чего вы ждёте без напоминаний: PM и разработчик учитывают это в каждой задаче. Из чата по задаче принцип добавляется кнопкой «Запомнить»."
      >
        <textarea
          rows={4}
          value={p.principles ?? ''}
          onChange={(e) => set('principles', orNull(e.target.value))}
          placeholder={'- Подписи и иконки совпадают с тем, что реально происходит\n- Меньше настроек и переходов, очевидное поведение по умолчанию'}
          className={inputClass}
        />
      </Field>

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
