'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Fetch on mount and every `intervalMs` while the tab is visible. A response
 * that arrives after `deps` changed is dropped, so a slow request made with old
 * parameters (e.g. before the stored project filter was read) can't overwrite
 * fresh data.
 */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const generation = useRef(0)

  const refresh = useCallback(async () => {
    const gen = generation.current
    try {
      const next = await fetcherRef.current()
      if (gen !== generation.current) return
      setData(next)
      setError(null)
    } catch (e) {
      if (gen === generation.current) setError(e as Error)
    }
  }, [])

  useEffect(() => {
    generation.current += 1
    let timer: ReturnType<typeof setInterval> | undefined
    const stop = () => {
      clearInterval(timer)
      timer = undefined
    }
    const start = () => {
      stop()
      refresh()
      timer = setInterval(refresh, intervalMs)
    }
    const onVisibility = () => (document.hidden ? stop() : start())
    start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, intervalMs, ...deps])

  return { data, error, refresh, setData }
}

/** localStorage-backed state; falls back to memory when storage is unavailable. */
export function useStoredState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(initial)
  useEffect(() => {
    try {
      const raw = localStorage.getItem(key)
      // Read after mount so the static prerender and the first client render match.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (raw !== null) setValue(JSON.parse(raw) as T)
    } catch {
      /* ignore */
    }
  }, [key])
  const update = useCallback(
    (next: T) => {
      setValue(next)
      try {
        localStorage.setItem(key, JSON.stringify(next))
      } catch {
        /* ignore */
      }
    },
    [key],
  )
  return [value, update] as const
}
