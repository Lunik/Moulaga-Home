import { useEffect, useSyncExternalStore } from 'react'
import { onlineManager } from '@tanstack/react-query'
import { registerSW } from 'virtual:pwa-register'

import { apiGet, queryString } from './api/client'
import type { Account, Household, SharedGoal } from './api/types'
import { localDateInputValue } from './ui'

interface WarmSummary {
  successful: number
  failed: number
}

let registrationPromise: Promise<ServiceWorkerRegistration | null> | null = null
let updateServiceWorker: ((reloadPage?: boolean) => Promise<void>) | null = null
let warmupInFlight: Promise<void> | null = null
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

export function useOfflineDataWarmup(isOnline: boolean): void {
  useEffect(() => {
    if (!isOnline) return
    void warmOfflineVisualData().catch((error: unknown) => {
      console.error("Le prechargement des vues hors ligne n'a pas pu aboutir.", error)
    })
  }, [isOnline])
}

function warmOfflineVisualData(): Promise<void> {
  if (warmupInFlight === null) {
    warmupInFlight = warmOfflineVisualDataInternal().finally(() => {
      warmupInFlight = null
    })
  }
  return warmupInFlight
}

async function warmOfflineVisualDataInternal(): Promise<void> {
  if (!onlineManager.isOnline() || !await waitForServiceWorkerControl()) return

  const anchorDate = localDateInputValue()
  const [accountsResult, householdsResult] = await Promise.allSettled([
    apiGet<Account[]>('/accounts?include_archived=true'),
    apiGet<Household[]>('/households'),
  ])
  const accounts = accountsResult.status === 'fulfilled' ? accountsResult.value : []
  const households = householdsResult.status === 'fulfilled' ? householdsResult.value : []
  const baseSummary = await warmPaths([
    `/accounts${queryString({ include_archived: true, as_of: anchorDate })}`,
    '/categories?include_archived=true',
    '/preferences',
    `/overview${queryString({ as_of: anchorDate })}`,
    `/stats/monthly${queryString({ as_of: anchorDate })}`,
    `/budget/overview${queryString({ on: anchorDate })}`,
    `/budget/envelopes${queryString({ on: anchorDate })}`,
    '/budget/envelopes',
    '/recurring',
    '/recurring/forecast?months=1',
    '/recurring/forecast?months=3',
    '/portfolio/summary',
    '/portfolio/allocation',
    '/portfolio/performance',
    '/networth/overview',
    '/networth/history',
    `/networth/overview${queryString({ as_of: anchorDate })}`,
    `/networth/history${queryString({ as_of: anchorDate })}`,
    '/holdings',
    '/debts',
    '/real-estate',
    '/contributions',
    ...(['cycle', 'year'] as const).flatMap((period) => [
      `/budget/cashflow${queryString({ on: anchorDate, period, by: 'source' })}`,
      `/budget/cashflow${queryString({ on: anchorDate, period, by: 'category' })}`,
      `/budget/spending${queryString({ on: anchorDate, period })}`,
    ]),
  ])

  const goalResults = await Promise.allSettled(
    households.map((household) => (
      apiGet<SharedGoal[]>(`/households/${household.id}/goals`)
    )),
  )
  const goals = goalResults.flatMap((result, index) => (
    result.status === 'fulfilled'
      ? result.value.map((goal) => ({ goal, householdId: households[index].id }))
      : []
  ))
  const accountTypes = [...new Set(accounts.map((account) => account.type))]
  const dynamicSummary = await warmPaths([
    ...[false, true].flatMap((archived) => [
      `/accounts/institution-history${queryString({ archived })}`,
      ...accountTypes.map((accountType) => (
        `/accounts/institution-history${queryString({
          archived,
          account_type: accountType,
        })}`
      )),
    ]),
    ...accounts.flatMap((account) => [
      `/accounts/${account.id}`,
      `/accounts/${account.id}/snapshots`,
      `/holdings${queryString({ account_id: account.id })}`,
    ]),
    ...households.map((household) => (
      `/households/${household.id}/shared-accounts`
    )),
    ...goals.map(({ goal, householdId }) => (
      `/households/${householdId}/goals/${goal.id}/contributions`
    )),
  ])

  const failed = baseSummary.failed
    + dynamicSummary.failed
    + Number(accountsResult.status === 'rejected')
    + Number(householdsResult.status === 'rejected')
    + goalResults.filter((result) => result.status === 'rejected').length
  if (failed > 0) {
    console.warn(`Cache PWA incomplet : ${failed} lecture(s) visuelle(s) indisponible(s).`)
  }
}

async function warmPaths(paths: string[]): Promise<WarmSummary> {
  const uniquePaths = [...new Set(paths)]
  const results = await Promise.allSettled(
    uniquePaths.map((path) => apiGet<unknown>(path)),
  )
  const failed = results.filter((result) => result.status === 'rejected').length
  return {
    successful: results.length - failed,
    failed,
  }
}

async function waitForServiceWorkerControl(): Promise<boolean> {
  registerPwa()
  if (registrationPromise === null) return false
  const registration = await registrationPromise
  if (registration === null) return false
  if (navigator.serviceWorker.controller) return true

  return new Promise((resolve) => {
    const onControllerChange = () => finish(true)
    const timeoutId = window.setTimeout(() => finish(false), 10_000)
    const finish = (controlled: boolean) => {
      window.clearTimeout(timeoutId)
      navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange)
      if (!controlled) {
        console.warn("Le service worker n'a pas pris le controle de la page a temps.")
      }
      resolve(controlled)
    }
    navigator.serviceWorker.addEventListener('controllerchange', onControllerChange)
    if (navigator.serviceWorker.controller) finish(true)
  })
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
