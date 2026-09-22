import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPost } from './api/client'
import type {
  UpdatePrompt,
  UpdatePromptCenter as UpdatePromptCenterData,
  UpdatePromptIgnoreResult,
  UpdatePromptPriority,
  UserProfile,
} from './api/types'
import type { Route } from './routing'
import { Icon, errorMessage } from './ui'

const priorityLabels: Record<UpdatePromptPriority, string> = {
  important: 'À compléter',
  review: 'À vérifier',
  suggestion: 'Suggestions',
}

export function UpdatePromptCenter({
  activeProfile,
  isOnline,
  navigate,
}: {
  activeProfile: UserProfile
  isOnline: boolean
  navigate: (route: Route) => void
}) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const prompts = useQuery({
    queryKey: ['update-prompts', activeProfile.id],
    queryFn: () => apiGet<UpdatePromptCenterData>('/update-prompts'),
    enabled: isOnline,
    staleTime: 30_000,
  })

  useEffect(() => {
    setOpen(false)
  }, [activeProfile.id])

  useEffect(() => {
    const refresh = () => {
      window.setTimeout(() => { void prompts.refetch() }, 250)
    }
    window.addEventListener('moulaga:data-mutated', refresh)
    return () => window.removeEventListener('moulaga:data-mutated', refresh)
  }, [prompts.refetch])

  useEffect(() => {
    if (!open) return
    const closeOnOutsideClick = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [open])

  const ignorePrompt = useMutation({
    mutationFn: (prompt: UpdatePrompt) => apiPost<UpdatePromptIgnoreResult>(
      `/update-prompts/${encodeURIComponent(prompt.id)}/ignore`,
    ),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: ['update-prompts', activeProfile.id],
      })
      if (result.mode === 'document') {
        await queryClient.invalidateQueries({ queryKey: ['documents'] })
      }
    },
  })
  const visiblePrompts = prompts.data?.prompts ?? []
  const actionCount = visiblePrompts.length
  const groupedPrompts = useMemo(
    () => (['important', 'review', 'suggestion'] as const)
      .map((priority) => ({
        priority,
        prompts: visiblePrompts.filter((prompt) => prompt.priority === priority),
      }))
      .filter((group) => group.prompts.length > 0),
    [visiblePrompts],
  )

  const activate = (prompt: UpdatePrompt) => {
    setOpen(false)
    navigate(routeForPrompt(prompt))
  }

  return (
    <div className="update-prompt-center" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={
          actionCount > 0
            ? `${actionCount} demande${actionCount > 1 ? 's' : ''} de mise à jour`
            : 'Demandes de mise à jour'
        }
        className={`notification-toggle${open ? ' active' : ''}`}
        disabled={!isOnline}
        onClick={() => setOpen((current) => !current)}
        title="Demandes de mise à jour"
        type="button"
      >
        <Icon name="bell" />
        {actionCount > 0 && (
          <span className="notification-badge">
            {actionCount > 99 ? '99+' : actionCount}
          </span>
        )}
      </button>
      {open && (
        <section
          aria-label="Demandes de mise à jour"
          className="update-prompt-popover"
          role="dialog"
        >
          <header>
            <div>
              <span className="eyebrow">Données à jour</span>
              <h2>À faire maintenant</h2>
            </div>
            <button
              aria-label="Fermer les demandes"
              className="icon-action"
              onClick={() => setOpen(false)}
              type="button"
            >
              <Icon name="close" />
            </button>
          </header>
          {prompts.error && (
            <p className="update-prompt-error" role="alert">
              Impossible de charger les demandes : {errorMessage(prompts.error)}
            </p>
          )}
          {prompts.isPending ? (
            <p className="update-prompt-empty">Recherche des informations à actualiser…</p>
          ) : groupedPrompts.length === 0 ? (
            <div className="update-prompt-empty">
              <Icon name="check" />
              <strong>Tout est à jour</strong>
              <span>Aucune information ne demande votre attention.</span>
            </div>
          ) : (
            <div className="update-prompt-groups">
              {groupedPrompts.map((group) => (
                <section className="update-prompt-group" key={group.priority}>
                  <h3>
                    {priorityLabels[group.priority]}
                    <span>{group.prompts.length}</span>
                  </h3>
                  <div className="update-prompt-list">
                    {group.prompts.map((prompt) => (
                      <article
                        className={`update-prompt-item ${prompt.priority}`}
                        key={prompt.id}
                      >
                        <span className="update-prompt-indicator">
                          <Icon name={iconForPrompt(prompt)} />
                        </span>
                        <span className="update-prompt-copy">
                          <strong>{prompt.title}</strong>
                          <small>{prompt.detail}</small>
                          <span className="update-prompt-actions">
                            <button
                              className="update-prompt-primary-action"
                              onClick={() => activate(prompt)}
                              type="button"
                            >
                              {prompt.action_label} <Icon name="arrow" />
                            </button>
                            <button
                              className="update-prompt-ignore"
                              disabled={ignorePrompt.isPending}
                              onClick={() => ignorePrompt.mutate(prompt)}
                              title={ignoreDescription(prompt)}
                              type="button"
                            >
                              {ignoreLabel(prompt)}
                            </button>
                          </span>
                        </span>
                      </article>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
          {ignorePrompt.error && (
            <p className="update-prompt-error" role="alert">
              Impossible d’ignorer la demande : {errorMessage(ignorePrompt.error)}
            </p>
          )}
          <footer>
            Ignorer masque temporairement une demande selon sa cadence (30 jours minimum).
            Un document est classé durablement parmi les documents ignorés.
          </footer>
        </section>
      )}
    </div>
  )
}

function ignoreDescription(prompt: UpdatePrompt) {
  if (prompt.ignore_mode === 'document') {
    return 'Classer ce document parmi les documents ignorés'
  }
  return `Masquer cette demande pendant ${prompt.recurrence_days ?? 30} jours`
}

function ignoreLabel(prompt: UpdatePrompt) {
  return prompt.ignore_mode === 'document'
    ? 'Ignorer'
    : `Ignorer · ${prompt.recurrence_days ?? 30} j`
}

function routeForPrompt(prompt: UpdatePrompt): Route {
  switch (prompt.target) {
    case 'account':
      return prompt.resource_id
        ? { name: 'account', accountId: prompt.resource_id }
        : { name: 'accounts' }
    case 'accounts':
      return { name: 'accounts' }
    case 'recurring':
      return prompt.resource_id
        ? { name: 'budget', tab: 'recurring', focusId: prompt.resource_id }
        : { name: 'budget', tab: 'recurring' }
    case 'holdings':
      return prompt.resource_id
        ? {
            name: 'wealth',
            tab: 'holdings',
            holdingsTab: 'positions',
            focusId: prompt.resource_id,
          }
        : { name: 'wealth', tab: 'holdings', holdingsTab: 'positions' }
    case 'holding_operations':
      return { name: 'wealth', tab: 'holdings', holdingsTab: 'operations' }
    case 'real_estate':
      return prompt.resource_id
        ? { name: 'wealth', tab: 'real-estate', focusId: prompt.resource_id }
        : { name: 'wealth', tab: 'real-estate' }
    case 'debts':
      return prompt.resource_id
        ? { name: 'wealth', tab: 'debts', focusId: prompt.resource_id }
        : { name: 'wealth', tab: 'debts' }
    case 'documents':
      return { name: 'documents', tab: 'missing' }
    case 'work_contract':
      return prompt.resource_id
        ? { name: 'work', tab: 'salary', focusId: prompt.resource_id }
        : { name: 'work', tab: 'salary' }
    case 'payslips':
      return { name: 'work', tab: 'salary' }
    case 'pension':
      return { name: 'work', tab: 'pension' }
  }
}

function iconForPrompt(prompt: UpdatePrompt) {
  switch (prompt.target) {
    case 'account':
    case 'accounts':
      return 'accounts' as const
    case 'recurring':
      return 'recurring' as const
    case 'holdings':
    case 'holding_operations':
      return 'holdings' as const
    case 'real_estate':
      return 'home' as const
    case 'debts':
      return 'debt' as const
    case 'documents':
      return 'attachment' as const
    case 'work_contract':
      return 'briefcase' as const
    case 'payslips':
      return 'receipt' as const
    case 'pension':
      return 'target' as const
  }
}
