'use client'

import { Pause, Play, Send } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button, Card, ErrorNote, Field, inputClass } from '@/components/ui'
import { api, type TelegramSettings } from '@/lib/api'
import { ago } from '@/lib/format'
import { usePoll } from '@/lib/hooks'

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <h1 className="text-xl font-semibold">Настройки</h1>
      <WorkerCard />
      <TelegramCard />
      <InstallHint />
    </div>
  )
}

function WorkerCard() {
  const status = usePoll(api.status, 5000)
  const [error, setError] = useState<string | null>(null)
  const s = status.data
  return (
    <Card className="space-y-3 p-4">
      <div className="font-semibold">Агенты</div>
      {s && (
        <>
          <div className="text-sm text-muted">
            Воркер {s.worker_online ? 'на связи' : 'не отвечает'}
            {s.worker_last_seen && ` · пульс ${ago(s.worker_last_seen)}`}
          </div>
          <div className="space-y-1">
            {s.slots.map((slot) => (
              <div key={slot.id} className="flex items-center gap-2 text-sm">
                <span className={`h-2 w-2 rounded-full ${slot.status === 'working' ? 'bg-ok' : 'bg-surface-2 ring-1 ring-line'}`} />
                <span className="font-mono text-xs text-muted">{slot.id}</span>
                <span className="truncate">{slot.task_title ? `#${slot.task_ticket} ${slot.task_title}` : 'свободен'}</span>
              </div>
            ))}
          </div>
          <Button
            variant={s.developers_enabled ? 'secondary' : 'primary'}
            onClick={async () => {
              try {
                await api.toggleDevelopers()
                await status.refresh()
              } catch (e) {
                setError((e as Error).message)
              }
            }}
          >
            {s.developers_enabled ? (
              <>
                <Pause size={16} /> Приостановить новые задачи
              </>
            ) : (
              <>
                <Play size={16} /> Возобновить работу
              </>
            )}
          </Button>
          <p className="text-xs text-muted">Пауза не прерывает текущие задачи — только не даёт брать новые.</p>
        </>
      )}
      <ErrorNote error={error ?? status.error} />
    </Card>
  )
}

function TelegramCard() {
  const [form, setForm] = useState<TelegramSettings | null>(null)
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.telegram().then(setForm, (e) => setNote({ ok: false, text: e.message }))
  }, [])

  async function run(fn: () => Promise<string>) {
    setBusy(true)
    setNote(null)
    try {
      setNote({ ok: true, text: await fn() })
    } catch (e) {
      setNote({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  if (!form) return null
  return (
    <Card className="space-y-4 p-4">
      <div className="flex items-center gap-2 font-semibold">
        <Send size={16} /> Telegram
      </div>
      <p className="text-sm text-muted">
        Бот присылает «на stage», ошибки и релизы, а обычное сообщение боту создаёт задачу.
      </p>
      <Field label="Токен бота" hint="от @BotFather; сохранённый токен показан маской">
        <input
          value={form.bot_token}
          onChange={(e) => setForm({ ...form, bot_token: e.target.value })}
          className={`${inputClass} font-mono text-sm`}
        />
      </Field>
      <Field label="Chat ID владельца" hint="напишите боту /start и нажмите «Найти»">
        <div className="flex gap-2">
          <input
            value={form.owner_chat_id}
            onChange={(e) => setForm({ ...form, owner_chat_id: e.target.value })}
            className={inputClass}
            inputMode="numeric"
          />
          <Button
            type="button"
            disabled={busy}
            onClick={() =>
              run(async () => {
                const r = await api.detectChat(form.bot_token)
                setForm({ ...form, owner_chat_id: r.chat_id })
                return `Нашёл чат ${r.name}`
              })
            }
          >
            Найти
          </Button>
        </div>
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() =>
            run(async () => {
              await api.saveTelegram(form)
              const hook = await api.setWebhook()
              return `Сохранено, вебхук: ${hook.webhook_url}`
            })
          }
        >
          Сохранить и подключить
        </Button>
        <Button
          disabled={busy}
          onClick={() =>
            run(async () => {
              const r = await api.testTelegram({ bot_token: form.bot_token, owner_chat_id: form.owner_chat_id })
              if (!r.success) throw new Error(r.message)
              return `${r.message}${r.bot_username ? ` (@${r.bot_username})` : ''}`
            })
          }
        >
          Тест
        </Button>
      </div>
      {note && (note.ok ? <div className="text-sm text-ok">{note.text}</div> : <ErrorNote error={note.text} />)}
    </Card>
  )
}

function InstallHint() {
  return (
    <Card className="space-y-1 p-4 text-sm text-muted">
      <div className="font-semibold text-fg">На главный экран</div>
      <p>iPhone: Safari → «Поделиться» → «На экран Домой». Android: Chrome → ⋮ → «Установить приложение».</p>
    </Card>
  )
}
