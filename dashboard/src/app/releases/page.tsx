'use client'

import { useEffect, useState, useCallback } from 'react'
import { getReleases, getTasks, type Release, type Task } from '@/lib/api'
import { Loader2 } from 'lucide-react'
import ReleaseCreate from '@/components/releases/ReleaseCreate'
import ReleaseDetail from '@/components/releases/ReleaseDetail'
import ReleaseHistory from '@/components/releases/ReleaseHistory'

function isActive(r: Release): boolean {
  return r.status !== 'deployed' && r.status !== 'failed' && r.status !== 'cancelled' && r.status !== 'reverted'
}

export default function ReleasesPage() {
  const [releases, setReleases] = useState<Release[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    const [r, t] = await Promise.all([getReleases(), getTasks()])
    setReleases(r)
    setTasks(t)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: '#3592C4' }} />
      </div>
    )
  }

  const activeRelease = releases.find(isActive) ?? null
  const pastReleases = releases.filter((r) => !isActive(r))
  const readyTasks = tasks.filter((t) => t.status === 'ready_to_release')

  return (
    <div className="space-y-10">
      {activeRelease ? (
        <ReleaseDetail
          release={activeRelease}
          allTasks={tasks}
          onUpdated={(updated) => {
            setReleases((prev) =>
              prev.map((r) => (r.id === updated.id ? updated : r))
            )
          }}
        />
      ) : (
        <ReleaseCreate
          readyTasks={readyTasks}
          onCreated={() => {
            setLoading(true)
            load()
          }}
        />
      )}

      <div className="max-w-4xl">
        <ReleaseHistory releases={pastReleases} />
      </div>
    </div>
  )
}
