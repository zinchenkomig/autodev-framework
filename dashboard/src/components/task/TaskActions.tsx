import {
  Check,
  CheckCircle2,
  ClipboardList,
  FileDiff,
  Globe,
  MessageCircleQuestion,
  MessageSquarePlus,
  RotateCw,
  Square,
  Trash2,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui'
import { api, type Chat, type Project, type Task } from '@/lib/api'
import { canCancel, canDelete, canRetry, cx, feedbackKind, isMerged, notStarted } from '@/lib/format'
import { feedbackTitle } from './FeedbackSheet'
import { PullRequests } from './PullRequests'

/** Everything the owner can do with the task; a button shows only when the API would take it. */
export function TaskActions({
  task: t,
  project,
  followUps,
  chats,
  busy,
  act,
  onFeedback,
  onAsk,
  onDelete,
}: {
  task: Task
  project?: Project
  followUps: Task[]
  /** The questions asked about this task. */
  chats: Chat[]
  busy: boolean
  /** Runs a request that returns the changed task and shows the result. */
  act: (request: () => Promise<Task>) => void
  onFeedback: () => void
  onAsk: () => void
  onDelete: () => void
}) {
  const merged = isMerged(t.status)
  const feedback = feedbackKind(t)
  const waiting = t.waiting_for.length > 0
  const asked = chats.filter((c) => c.question).length
  const undecided = chats.some((c) => c.pending > 0)

  function reject() {
    const reason = prompt('Почему не нужно? Скаут и PM это учтут. Можно оставить пустым.')
    if (reason !== null) act(() => api.rejectTask(t.id, reason))
  }

  return (
    <div className="flex flex-wrap gap-2">
      {t.status === 'proposed' && (
        <>
          <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => api.approveTask(t.id))}>
            <Check size={15} /> В работу
          </Button>
          <Button size="sm" disabled={busy} onClick={reject}>
            <X size={15} /> Отклонить
          </Button>
        </>
      )}
      {t.full_diff?.url && (
        <a href={t.full_diff.url} target="_blank" rel="noreferrer">
          <Button size="sm" title={`Код задачи и доработок одним сравнением на GitHub (${t.full_diff.tasks} PR)`}>
            <FileDiff size={15} /> Весь код
          </Button>
        </a>
      )}
      <PullRequests task={t} followUps={followUps} />
      {merged && project?.stage_url && (
        <a href={project.stage_url} target="_blank" rel="noreferrer">
          <Button size="sm" variant={t.status === 'on_stage' ? 'primary' : 'secondary'}>
            <Globe size={15} /> Открыть stage
          </Button>
        </a>
      )}
      {/* A follow-up is checked with its main task, by its one plan. */}
      {merged && !t.parent && (
        <Button
          size="sm"
          disabled={busy || (waiting && !t.verified_at)}
          className={cx(t.verified_at && 'border-ok/40 text-ok')}
          onClick={() =>
            (!t.verified_at || confirm('Снять отметку «проверено»?')) && act(() => api.verifyTask(t.id, !t.verified_at))
          }
        >
          <CheckCircle2 size={15} /> {t.verified_at ? 'Проверено' : 'Отметить проверенным'}
        </Button>
      )}
      {feedback && (
        <Button size="sm" onClick={onFeedback}>
          <MessageSquarePlus size={15} /> {feedbackTitle(feedback)}
        </Button>
      )}
      <Button size="sm" onClick={onAsk}>
        <MessageCircleQuestion size={15} /> Спросить{asked > 0 && <span className="text-muted">· {asked}</span>}
        {undecided && <span className="h-2 w-2 rounded-full bg-warn" title="Есть предложение агента, ждёт решения" />}
      </Button>
      {notStarted(t) && !t.brief && (
        <Button
          size="sm"
          disabled={busy}
          title="PM продумывает задачу до кода. Выключите для очевидной задачи или если хотите решить всё сами."
          onClick={() => act(() => api.updateTask(t.id, { pm: !t.pm }))}
        >
          <ClipboardList size={15} /> {t.pm ? 'PM: вкл' : 'PM: выкл'}
        </Button>
      )}
      {canRetry(t.status) && (
        <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => api.retryTask(t.id))}>
          <RotateCw size={15} /> Повторить
        </Button>
      )}
      {canCancel(t.status) && (
        <Button size="sm" variant="danger" disabled={busy} onClick={() => confirm('Остановить задачу?') && act(() => api.cancelTask(t.id))}>
          <Square size={14} /> Стоп
        </Button>
      )}
      {canDelete(t.status) && (
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => confirm('Удалить задачу?') && onDelete()}>
          <Trash2 size={15} />
        </Button>
      )}
    </div>
  )
}
