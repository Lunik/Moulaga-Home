import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPost, queryString } from '../api/client'
import type {
  Account,
  GoalContribution,
  Household,
  HouseholdMember,
  SharedAccount,
  SharedGoal,
} from '../api/types'
import {
  EmptyState,
  Field,
  FormInput,
  FormSelect,
  Icon,
  InstitutionLogo,
  Panel,
  ProgressBar,
  StatusBadge,
  errorMessage,
  formatDate,
  initials,
  money,
} from '../ui'

export function FamilyView({ accounts }: { accounts: Account[] }) {
  const queryClient = useQueryClient()
  const [selectedHouseholdId, setSelectedHouseholdId] = useState<number | null>(null)
  const [selectedActorId, setSelectedActorId] = useState<number | null>(null)
  const [showHouseholdForm, setShowHouseholdForm] = useState(false)
  const households = useQuery({
    queryKey: ['households'],
    queryFn: () => apiGet<Household[]>('/households'),
  })
  const activeHouseholdId = selectedHouseholdId ?? households.data?.[0]?.id ?? null
  const activeHousehold = households.data?.find((household) => household.id === activeHouseholdId)
  const members = activeHousehold?.members ?? []
  const sharedAccounts = useQuery({
    queryKey: ['shared-accounts', activeHouseholdId],
    queryFn: () => apiGet<SharedAccount[]>(`/households/${activeHouseholdId}/shared-accounts`),
    enabled: activeHouseholdId !== null,
  })
  const goals = useQuery({
    queryKey: ['shared-goals', activeHouseholdId],
    queryFn: () => apiGet<SharedGoal[]>(`/households/${activeHouseholdId}/goals`),
    enabled: activeHouseholdId !== null,
  })
  const activeActor = members.find((member) => member.id === selectedActorId)
    ?? members.find((member) => member.role === 'owner')
    ?? members[0]
  const errors = [households.error, sharedAccounts.error, goals.error].filter(Boolean)

  if (!households.isLoading && (households.data?.length ?? 0) === 0 && !showHouseholdForm) {
    return (
      <Panel title="Famille" subtitle="Créez un espace local avant de partager des objectifs ou des comptes.">
        <EmptyState
          icon="family"
          title="Aucun foyer configuré"
          text="Les données restent sur cette instance. Les rôles contrôleront chaque modification."
          action={(
            <button className="primary-button" type="button" onClick={() => setShowHouseholdForm(true)}>
              <Icon name="plus" /> Créer un foyer
            </button>
          )}
        />
      </Panel>
    )
  }

  return (
    <div className="view-stack">
      <section className="section-intro">
        <div>
          <p>Comptes et objectifs partagés avec contrôle des rôles.</p>
          {activeActor && <small>Profil actif : {activeActor.name} · {roleLabel(activeActor.role)}</small>}
        </div>
        <div className="header-actions">
          {(households.data?.length ?? 0) > 1 && (
            <FormSelect value={activeHouseholdId ?? ''} onChange={(event) => setSelectedHouseholdId(Number(event.target.value))}>
              {households.data?.map((household) => <option key={household.id} value={household.id}>{household.name}</option>)}
            </FormSelect>
          )}
          {members.length > 0 && (
            <FormSelect
              aria-label="Profil actif"
              value={activeActor?.id ?? ''}
              onChange={(event) => setSelectedActorId(Number(event.target.value))}
            >
              {members.map((member) => (
                <option key={member.id} value={member.id}>{member.name} · {roleLabel(member.role)}</option>
              ))}
            </FormSelect>
          )}
          <button className="secondary-button" type="button" onClick={() => setShowHouseholdForm((current) => !current)}>
            <Icon name="plus" /> Nouveau foyer
          </button>
        </div>
      </section>

      {showHouseholdForm && (
        <HouseholdForm
          onCancel={() => setShowHouseholdForm(false)}
          onSaved={async (household) => {
            await queryClient.invalidateQueries({ queryKey: ['households'] })
            setSelectedHouseholdId(household.id)
            setShowHouseholdForm(false)
          }}
        />
      )}

      {errors.length > 0 && <div className="error-banner">{errorMessage(errors[0])}</div>}

      {activeHouseholdId !== null && (
        <>
          <section className="family-hero">
            <span className="family-mark"><Icon name="family" /></span>
            <div>
              <p className="eyebrow">Espace partagé</p>
              <h2>{activeHousehold?.name}</h2>
              <p>
                {members.length} membre{members.length === 1 ? '' : 's'} ·{' '}
                {(sharedAccounts.data ?? []).length} compte{sharedAccounts.data?.length === 1 ? '' : 's'} partagé
                {sharedAccounts.data?.length === 1 ? '' : 's'}
              </p>
            </div>
            <strong>
              {money((sharedAccounts.data ?? []).reduce(
                (sum, account) => sum + Number(account.balance ?? accounts.find((item) => item.id === account.account_id)?.balance ?? 0),
                0,
              ))}
            </strong>
          </section>

          <section className="dashboard-grid">
            <Panel
              title="Comptes partagés"
              subtitle="Derniers relevés disponibles, sans double comptage."
              action={activeActor && ['owner', 'admin'].includes(activeActor.role) ? (
                <ShareAccountForm
                  accounts={accounts}
                  actorId={activeActor.id}
                  householdId={activeHouseholdId}
                  onSaved={() => queryClient.invalidateQueries({ queryKey: ['shared-accounts', activeHouseholdId] })}
                />
              ) : undefined}
            >
              {(sharedAccounts.data ?? []).length > 0 ? (
                <div className="shared-account-grid">
                  {sharedAccounts.data?.map((account) => {
                    const linkedAccount = accounts.find((item) => item.id === account.account_id)
                    return (
                      <article key={account.id}>
                        <InstitutionLogo institution={linkedAccount?.institution} />
                        <div>
                          <strong>{account.account_name ?? linkedAccount?.name ?? `Compte ${account.account_id}`}</strong>
                          <small>Compte partagé</small>
                        </div>
                        <strong>{money(account.balance ?? linkedAccount?.balance)}</strong>
                      </article>
                    )
                  })}
                </div>
              ) : (
                <EmptyState icon="accounts" text="Aucun compte partagé dans ce foyer." />
              )}
            </Panel>

            <Panel
              title="Membres"
              subtitle="Les propriétaires et éditeurs peuvent modifier les données."
              action={activeActor && ['owner', 'admin'].includes(activeActor.role) ? (
                <MemberForm
                  actorId={activeActor.id}
                  householdId={activeHouseholdId}
                  onSaved={() => queryClient.invalidateQueries({ queryKey: ['households'] })}
                />
              ) : undefined}
            >
              <div className="member-list">
                {members.map((member) => (
                  <div key={member.id}>
                    <span className="entity-avatar">{initials(member.name)}</span>
                    <span><strong>{member.name}</strong><small>Profil local</small></span>
                    <StatusBadge tone={member.role === 'owner' ? 'primary' : 'neutral'}>{roleLabel(member.role)}</StatusBadge>
                  </div>
                ))}
              </div>
            </Panel>
          </section>

          <Panel
            title="Objectifs partagés"
            subtitle="Suivez les contributions de chaque membre."
            action={activeActor && activeActor.role !== 'viewer' ? (
              <GoalForm
                actorId={activeActor.id}
                householdId={activeHouseholdId}
                onSaved={() => queryClient.invalidateQueries({ queryKey: ['shared-goals', activeHouseholdId] })}
              />
            ) : undefined}
          >
            {(goals.data ?? []).length > 0 ? (
              <div className="goal-grid">
                {goals.data?.map((goal) => (
                  <GoalCard
                    actor={activeActor}
                    goal={goal}
                    householdId={activeHouseholdId}
                    key={goal.id}
                    members={members}
                    onSaved={() => queryClient.invalidateQueries({ queryKey: ['shared-goals', activeHouseholdId] })}
                  />
                ))}
              </div>
            ) : (
              <EmptyState icon="target" text="Aucun objectif partagé." />
            )}
          </Panel>
        </>
      )}
    </div>
  )
}

function HouseholdForm({
  onCancel,
  onSaved,
}: {
  onCancel: () => void
  onSaved: (household: Household) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [ownerName, setOwnerName] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<Household>('/households', { name, owner_name: ownerName }),
    onSuccess: onSaved,
  })
  return (
    <Panel title="Nouveau foyer" subtitle="Le premier profil devient propriétaire de cet espace local.">
      <form className="inline-form" onSubmit={(event: FormEvent) => {
        event.preventDefault()
        mutation.mutate()
      }}>
        <Field label="Nom du foyer">
          <FormInput value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
        </Field>
        <Field label="Nom du profil propriétaire">
          <FormInput value={ownerName} onChange={(event) => setOwnerName(event.target.value)} maxLength={120} required />
        </Field>
        <div className="form-buttons">
          <button className="secondary-button" type="button" onClick={onCancel}>Annuler</button>
          <button className="primary-button" type="submit" disabled={mutation.isPending}>Créer</button>
        </div>
      </form>
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </Panel>
  )
}

function MemberForm({
  actorId,
  householdId,
  onSaved,
}: {
  actorId: number
  householdId: number
  onSaved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<'admin' | 'member' | 'viewer'>('viewer')
  const mutation = useMutation({
    mutationFn: () => apiPost<HouseholdMember>(
      `/households/${householdId}/members${queryString({ actor_id: actorId })}`,
      { name: displayName, role },
    ),
    onSuccess: async () => {
      setOpen(false)
      setDisplayName('')
      await onSaved()
    },
  })
  if (!open) return <button className="secondary-button small-button" type="button" onClick={() => setOpen(true)}><Icon name="plus" /> Membre</button>
  return (
    <form className="compact-inline-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <FormInput aria-label="Nom du membre" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
      <FormSelect aria-label="Rôle" value={role} onChange={(event) => setRole(event.target.value as 'admin' | 'member' | 'viewer')}>
        <option value="admin">Administrateur</option>
        <option value="member">Membre</option>
        <option value="viewer">Lecture</option>
      </FormSelect>
      <button className="primary-button icon-button" type="submit" aria-label="Ajouter"><Icon name="check" /></button>
      <button className="text-button icon-button" type="button" aria-label="Annuler" onClick={() => setOpen(false)}><Icon name="close" /></button>
      {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
    </form>
  )
}

function ShareAccountForm({
  accounts,
  actorId,
  householdId,
  onSaved,
}: {
  accounts: Account[]
  actorId: number
  householdId: number
  onSaved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [accountId, setAccountId] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<SharedAccount>(
      `/households/${householdId}/shared-accounts${queryString({ actor_id: actorId })}`,
      { account_id: Number(accountId || accounts[0]?.id), permission: 'edit' },
    ),
    onSuccess: async () => {
      setOpen(false)
      await onSaved()
    },
  })
  if (!open) return <button className="secondary-button small-button" type="button" onClick={() => setOpen(true)}><Icon name="plus" /> Partager</button>
  return (
    <form className="compact-inline-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <FormSelect aria-label="Compte à partager" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
        {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
      </FormSelect>
      <button className="primary-button icon-button" type="submit" aria-label="Partager" disabled={accounts.length === 0}><Icon name="check" /></button>
      <button className="text-button icon-button" type="button" aria-label="Annuler" onClick={() => setOpen(false)}><Icon name="close" /></button>
      {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
    </form>
  )
}

function GoalForm({
  actorId,
  householdId,
  onSaved,
}: {
  actorId: number
  householdId: number
  onSaved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [target, setTarget] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost<SharedGoal>(
      `/households/${householdId}/goals${queryString({ actor_id: actorId })}`,
      { name, target_amount: target, current_amount: '0', due_date: null, account_id: null },
    ),
    onSuccess: async () => {
      setOpen(false)
      setName('')
      setTarget('')
      await onSaved()
    },
  })
  if (!open) return <button className="secondary-button small-button" type="button" onClick={() => setOpen(true)}><Icon name="plus" /> Objectif</button>
  return (
    <form className="compact-inline-form" onSubmit={(event) => {
      event.preventDefault()
      mutation.mutate()
    }}>
      <FormInput aria-label="Nom de l'objectif" value={name} onChange={(event) => setName(event.target.value)} required />
      <FormInput aria-label="Montant cible" type="number" min="0.01" step="0.01" value={target} onChange={(event) => setTarget(event.target.value)} required />
      <button className="primary-button icon-button" type="submit" aria-label="Créer"><Icon name="check" /></button>
      <button className="text-button icon-button" type="button" aria-label="Annuler" onClick={() => setOpen(false)}><Icon name="close" /></button>
      {mutation.error && <span className="form-error">{errorMessage(mutation.error)}</span>}
    </form>
  )
}

function GoalCard({
  actor,
  goal,
  householdId,
  members,
  onSaved,
}: {
  actor?: HouseholdMember
  goal: SharedGoal
  householdId: number
  members: HouseholdMember[]
  onSaved: () => Promise<void>
}) {
  const [amount, setAmount] = useState('')
  const contributions = useQuery({
    queryKey: ['goal-contributions', goal.id],
    queryFn: () => apiGet<GoalContribution[]>(`/households/${householdId}/goals/${goal.id}/contributions`),
  })
  const mutation = useMutation({
    mutationFn: () => apiPost<GoalContribution>(
      `/households/${householdId}/goals/${goal.id}/contributions${queryString({ actor_id: actor?.id })}`,
      { member_id: actor?.id, amount, occurred_on: localDate(), note: null },
    ),
    onSuccess: async () => {
      setAmount('')
      await contributions.refetch()
      await onSaved()
    },
  })
  const percentage = Number(goal.target_amount) > 0
    ? (Number(goal.current_amount) / Number(goal.target_amount)) * 100
    : 0
  return (
    <article className="goal-card">
      <div className="goal-head">
        <span><i style={{ background: '#314ac8' }} /><strong>{goal.name}</strong></span>
        {goal.due_date && <small>{formatDate(goal.due_date)}</small>}
      </div>
      <div className="goal-values">
        <strong>{money(goal.current_amount)}</strong>
        <span>sur {money(goal.target_amount)}</span>
      </div>
      <ProgressBar value={percentage} color="#314ac8" />
      {(contributions.data ?? []).length > 0 && (
        <div className="contribution-summary">
          {contributions.data?.slice(0, 3).map((contribution) => (
            <span key={contribution.id}>
              {contribution.member_name ?? members.find((member) => member.id === contribution.member_id)?.name ?? 'Contribution'}
              {' '}<strong>{money(contribution.amount)}</strong>
            </span>
          ))}
        </div>
      )}
      {actor && actor.role !== 'viewer' && (
        <form className="goal-contribution-form" onSubmit={(event) => {
          event.preventDefault()
          mutation.mutate()
        }}>
          <FormInput type="number" min="0.01" step="0.01" placeholder="Contribution" value={amount} onChange={(event) => setAmount(event.target.value)} required />
          <button className="primary-button small-button" type="submit">Contribuer</button>
        </form>
      )}
      {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
    </article>
  )
}

function roleLabel(role: HouseholdMember['role']): string {
  return { owner: 'Propriétaire', admin: 'Administrateur', member: 'Membre', viewer: 'Lecture' }[role]
}

function localDate(): string {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}
