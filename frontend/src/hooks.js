import { useCallback, useEffect, useRef, useState } from 'react'

// Poll an async loader. Keeps the last good data on refresh errors and exposes loading/error state.
export function usePoll(loader, deps = [], interval = 3000) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const loaderRef = useRef(loader)
  loaderRef.current = loader
  const alive = useRef(true)

  const load = useCallback(async () => {
    try {
      const data = await loaderRef.current()
      if (alive.current) setState({ data, error: null, loading: false })
    } catch (error) {
      if (alive.current) setState((s) => ({ data: s.data, error, loading: false }))
    }
  }, [])

  useEffect(() => {
    alive.current = true
    setState((s) => ({ ...s, loading: true }))
    load()
    const t = interval ? setInterval(load, interval) : null
    return () => {
      alive.current = false
      if (t) clearInterval(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, interval])

  return { ...state, reload: load }
}
