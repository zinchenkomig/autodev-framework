'use client'

import { useState } from 'react'
import type { NewRepo, ProjectInput, Repo, ScoutMode } from '@/lib/api'
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
  idea: null,
  principles: null,
  scout: 'off',
  stage_limit: 10,
  model: null,
  max_parallel: 1,
  enabled: true,
}

const SCOUT_MODES: { value: ScoutMode; label: string; hint: string }[] = [
  { value: 'off', label: 'Выключен', hint: 'Сам не ходит. Можно запустить кнопкой на странице проекта: находки станут предложениями.' },
  { value: 'propose', label: 'Предлагает', hint: 'Когда проект простаивает, набирает предложения до лимита и присылает пачкой. В работу идёт только то, что вы примете; следующая пачка — когда разберёте эту.' },
  { value: 'auto', label: 'Сам в работу', hint: 'Всё, что нашёл, сразу идёт в разработку и на stage, без вашего решения. Релиз в прод остаётся за вами.' },
]

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
          stage_url: orNull(p.stage_url ?? ''),
          model: orNull(p.model ?? ''),
          idea: orNull(p.idea ?? ''),
          principles: orNull(p.principles ?? ''),
          instructions: orNull(p.instructions ?? ''),
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
        {newRepo && (
          <>
            <Field
              label="Что строим"
              hint="Идея продукта и первая задача: агент выберет стек и заложит каркас — код, тесты, CI, CLAUDE.md."
            >
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
        )}
      </div>

      <Field label="URL stage" hint={newRepo ? 'пусто — выдадим для проекта в организации' : undefined}>
        <input
          type="url"
          placeholder="https://stage.example.com"
          value={p.stage_url ?? ''}
          onChange={(e) => set('stage_url', e.target.value || null)}
          className={inputClass}
        />
      </Field>

      {!newRepo && (
        <Field
          label="Идея продукта"
          hint="Что это и для кого, своими словами. Скаут сверяет с ней продукт: чего не хватает и что лишнее. PM держит задачи в её рамках."
        >
          <textarea
            rows={4}
            value={p.idea ?? ''}
            onChange={(e) => set('idea', e.target.value || null)}
            placeholder="Учу слова карточками по 5 минут в день: добавил список — и сразу учишь, без настроек."
            className={inputClass}
          />
        </Field>
      )}

      <Field
        label="Принципы продукта"
        hint="Чего вы ждёте без напоминаний: агенты учитывают это в каждой задаче. Из чата по задаче принцип добавляется кнопкой «Запомнить»."
      >
        <textarea
          rows={4}
          value={p.principles ?? ''}
          onChange={(e) => set('principles', e.target.value || null)}
          placeholder={'- Подписи и иконки совпадают с тем, что реально происходит\n- Меньше настроек и переходов, очевидное поведение по умолчанию'}
          className={inputClass}
        />
      </Field>

      <div className="space-y-3 rounded-2xl border border-line p-3">
        <Field label="Скаут" hint={SCOUT_MODES.find((m) => m.value === p.scout)?.hint}>
          <div className="flex flex-wrap gap-2">
            {SCOUT_MODES.map((mode) => (
              <button
                key={mode.value}
                type="button"
                onClick={() => set('scout', mode.value)}
                className={cx(
                  'rounded-full border px-3 py-1.5 text-sm',
                  p.scout === mode.value ? 'border-accent bg-accent text-accent-fg' : 'border-line bg-surface text-muted',
                )}
              >
                {mode.label}
              </button>
            ))}
          </div>
        </Field>
        <Field label="Лимит задач на stage" hint="Вместе с доработками, задачами в работе и предложениями. Дальше скаут ждёт релиза; ваши задачи лимит не держит.">
          <input
            type="number"
            required
            min={1}
            max={100}
            value={p.stage_limit || ''}
            onChange={(e) => set('stage_limit', Number(e.target.value))}
            className={inputClass}
          />
        </Field>
      </div>

      <label className="flex items-start gap-3">
        <input type="checkbox" checked={p.pm} onChange={(e) => set('pm', e.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 accent-[var(--accent)]" />
        <span className="text-sm">
          PM продумывает задачи перед разработкой
          <span className="block text-muted">Значение по умолчанию для новых задач; у задачи можно выключить.</span>
        </span>
      </label>

      {/* What a project rarely needs changed: the defaults work. */}
      <details className="rounded-2xl border border-line p-3">
        <summary className="cursor-pointer text-sm font-medium">Дополнительно</summary>
        <div className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Ветка stage">
              <input required value={p.base_branch} onChange={(e) => set('base_branch', e.target.value)} className={inputClass} />
            </Field>
            <Field label="Ветка прода">
              <input required value={p.prod_branch} onChange={(e) => set('prod_branch', e.target.value)} className={inputClass} />
            </Field>
            <Field label="Модель Claude" hint="пусто — по умолчанию">
              <input
                placeholder="opus / sonnet"
                value={p.model ?? ''}
                onChange={(e) => set('model', e.target.value || null)}
                className={inputClass}
              />
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
          </div>
          {!newRepo && (
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
          <Field label="Инструкции для агента" hint="Дополнение к CLAUDE.md репозитория.">
            <textarea
              rows={4}
              value={p.instructions ?? ''}
              onChange={(e) => set('instructions', e.target.value || null)}
              className={inputClass}
            />
          </Field>
          <label className="flex items-center gap-3">
            <input type="checkbox" checked={p.enabled} onChange={(e) => set('enabled', e.target.checked)} className="h-5 w-5 accent-[var(--accent)]" />
            <span className="text-sm">Агенты работают над проектом</span>
          </label>
        </div>
      </details>

      <ErrorNote error={error} />
      <Button type="submit" variant="primary" disabled={busy} className="w-full sm:w-auto">
        {busy ? 'Сохраняю…' : isNew ? 'Создать проект' : 'Сохранить'}
      </Button>
    </form>
  )
}
