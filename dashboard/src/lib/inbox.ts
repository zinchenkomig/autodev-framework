import { api, type Project, type Task } from './api'

/** What is waiting for the owner: nothing moves on until they act. */
export interface Inbox {
  /** On stage, ready for the owner's check (follow-ups are checked with their main task). */
  check: Task[]
  /** Failed: retry, send a fix or cancel. */
  failed: Task[]
  /** Projects whose every change on stage is checked and no release is open yet. */
  release: { project: Project; tasks: number }[]
  total: number
}

export async function fetchInbox(): Promise<Inbox> {
  const [tasks, projects, releases] = await Promise.all([
    api.tasksIn(['on_stage', 'failed']),
    api.projects(),
    api.releases(),
  ])
  const onStage = tasks.filter((t) => t.status === 'on_stage' && !(t.parent && t.test_plan.length === 0))
  const check = onStage.filter((t) => !t.verified_at && t.waiting_for.length === 0)
  const failed = tasks.filter((t) => t.status === 'failed')
  const releasing = new Set(releases.filter((r) => r.status === 'pending').map((r) => r.project_id))
  const release = projects
    .filter((p) => !releasing.has(p.id))
    .map((project) => {
      const mine = onStage.filter((t) => t.project_id === project.id)
      return { project, tasks: mine.length, ready: mine.length > 0 && mine.every((t) => t.verified_at) }
    })
    .filter((r) => r.ready)
    .map(({ project, tasks }) => ({ project, tasks }))
  return { check, failed, release, total: check.length + failed.length + release.length }
}
