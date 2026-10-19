import type { Task, TaskStatus } from './api'

/** A main task with its follow-ups stacked into it: one card, one test plan. */
export interface Stack {
  task: Task
  followUps: Task[]
  /** The follow-up that decides where the card stands (still in the works), if any. */
  active: Task | null
}

// What still needs attention goes first: the card stands where its least finished part is.
const URGENCY: TaskStatus[] = ['failed', 'in_progress', 'ci', 'deploying', 'queued', 'on_stage', 'released', 'cancelled']

/** Folds follow-ups into their main task when it is in *tasks*; keeps the order of *tasks*. */
export function stack(tasks: Task[]): Stack[] {
  const ids = new Set(tasks.map((t) => t.id))
  const stacks = new Map<string, Stack>()
  for (const t of tasks) {
    const key = t.parent && ids.has(t.parent.id) ? t.parent.id : t.id
    const s = stacks.get(key) ?? { task: t, followUps: [], active: null }
    if (key === t.id) s.task = t
    else s.followUps.push(t)
    stacks.set(key, s)
  }
  for (const s of stacks.values()) {
    const rank = (t: Task) => URGENCY.indexOf(t.status)
    const open = s.followUps.filter((f) => f.status !== 'cancelled' && rank(f) < rank(s.task))
    s.active = open.sort((a, b) => rank(a) - rank(b))[0] ?? null
  }
  return [...stacks.values()]
}

/** The status the stack shows on the board. */
export function stackStatus(s: Stack): TaskStatus {
  return (s.active ?? s.task).status
}
