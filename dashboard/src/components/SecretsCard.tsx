'use client'

import { KeyRound, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Badge, Button, Card, ErrorNote, Field, inputClass } from '@/components/ui'
import { api, type ProjectSecrets, type SecretEnv } from '@/lib/api'
import { usePoll } from '@/lib/hooks'

const ENVS: SecretEnv[] = ['stage', 'prod']
const NAME = /^[A-Z_][A-Z0-9_]*$/

/** The owner's keys for a deployed project: sealed with the cluster's key, committed to its repo. */
export function SecretsCard({ projectId }: { projectId: string }) {
  const secrets = usePoll(() => api.secrets(projectId), 60000, [projectId])
  const [name, setName] = useState('')
  const [value, setValue] = useState('')
  const [envs, setEnvs] = useState<SecretEnv[]>(ENVS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const data = secrets.data
  if (!data?.deployed) return null

  async function run(action: () => Promise<ProjectSecrets>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      await secrets.refresh()
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusy(false)
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault()
    // One env after the other: each is a commit to the same file.
    const ok = await run(async () => {
      let last: ProjectSecrets | undefined
      for (const env of envs) last = await api.setSecret(projectId, env, name, value)
      return last!
    })
    if (ok) {
      setName('')
      setValue('')
    }
  }

  async function remove(env: SecretEnv, key: string) {
    if (!confirm(`Удалить ${key} из ${env}?`)) return
    await run(() => api.deleteSecret(projectId, env, key))
  }

  const toggle = (env: SecretEnv) => setEnvs((prev) => (prev.includes(env) ? prev.filter((x) => x !== env) : [...prev, env]))
  const nameOk = NAME.test(name)

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2">
        <KeyRound size={18} className="text-accent" />
        <span className="font-semibold">Секреты</span>
      </div>
      <p className="text-sm text-muted">
        Приходят в приложение переменными окружения. Значение шифруется ключом кластера и коммитится в репозиторий —
        прочитать его потом нельзя, только заменить. Применяется после пересборки образа, через пару минут.
      </p>

      {ENVS.map((env) => (
        <div key={env} className="space-y-1">
          <div className="text-xs font-semibold uppercase text-muted">{env}</div>
          {data[env].length === 0 ? (
            <div className="text-sm text-muted">нет</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {data[env].map((key) => (
                <Badge key={key} className="font-mono">
                  {key}
                  <button onClick={() => remove(env, key)} disabled={busy} aria-label={`Удалить ${key}`} className="hover:text-bad">
                    <Trash2 size={12} />
                  </button>
                </Badge>
              ))}
            </div>
          )}
        </div>
      ))}

      <form onSubmit={save} className="space-y-3 border-t border-line pt-3">
        <Field label="Имя" hint="Например STRIPE_KEY. Такое же имя заменит значение.">
          <input
            value={name}
            onChange={(e) => setName(e.target.value.toUpperCase())}
            className={`${inputClass} font-mono`}
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field label="Значение">
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className={`${inputClass} font-mono`}
            autoComplete="new-password"
          />
        </Field>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          {ENVS.map((env) => (
            <label key={env} className="inline-flex items-center gap-1.5">
              <input type="checkbox" checked={envs.includes(env)} onChange={() => toggle(env)} />
              {env}
            </label>
          ))}
          <Button type="submit" variant="primary" size="sm" className="ml-auto" disabled={busy || !nameOk || !value || !envs.length}>
            {busy ? 'Сохраняю…' : 'Сохранить'}
          </Button>
        </div>
      </form>
      <ErrorNote error={error ?? secrets.error} />
    </Card>
  )
}
