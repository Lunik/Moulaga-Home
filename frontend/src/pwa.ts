import { useSyncExternalStore } from 'react'
import { onlineManager } from '@tanstack/react-query'
import { registerSW } from 'virtual:pwa-register'

let registrationPromise: Promise<ServiceWorkerRegistration | null> | null = null
let updateServiceWorker: ((reloadPage?: boolean) => Promise<void>) | null = null
let connectivityMonitorStarted = false
let serverOnline = navigator.onLine
const connectivityListeners = new Set<() => void>()

export function registerPwa(): void {
  startConnectivityMonitor()
  if (registrationPromise !== null) return
  if (!('serviceWorker' in navigator)) {
    registrationPromise = Promise.resolve(null)
    return
  }

  registrationPromise = new Promise((resolve) => {
    updateServiceWorker = registerSW({
      immediate: true,
      onNeedRefresh: () => {
        void updateServiceWorker?.(true)
      },
      onRegisteredSW: (_serviceWorkerUrl, registration) => {
        resolve(registration ?? null)
      },
      onRegisterError: (error: unknown) => {
        console.error("Le service worker de Moulaga n'a pas pu etre enregistre.", error)
        resolve(null)
      },
    })
  })
}

export function useOnlineStatus(): boolean {
  return useSyncExternalStore(
    (onStoreChange) => {
      connectivityListeners.add(onStoreChange)
      return () => {
        connectivityListeners.delete(onStoreChange)
      }
    },
    () => serverOnline,
    () => true,
  )
}

function startConnectivityMonitor(): void {
  if (connectivityMonitorStarted) return
  connectivityMonitorStarted = true
  onlineManager.setOnline(serverOnline)

  window.addEventListener('offline', () => setServerOnline(false))
  window.addEventListener('online', () => void checkServerConnection())
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void checkServerConnection()
  })
  window.setInterval(() => void checkServerConnection(), 15_000)
  void checkServerConnection()
}

async function checkServerConnection(): Promise<void> {
  if (!navigator.onLine) {
    setServerOnline(false)
    return
  }

  try {
    const response = await fetch('/api/health', {
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
    setServerOnline(response.ok)
  } catch {
    setServerOnline(false)
  }
}

function setServerOnline(online: boolean): void {
  if (serverOnline === online) return
  serverOnline = online
  onlineManager.setOnline(online)
  for (const listener of connectivityListeners) listener()
}
