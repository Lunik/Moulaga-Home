import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { advanceProfileSessionGeneration, ApiError } from './api/client'
import { profileQueryKeys, profilesApi } from './api/profiles'
import type { ProfileSession, UserProfile } from './api/types'
import { PinKeypad } from './PinKeypad'
import { Icon, errorMessage } from './ui'

const profileColors = ['#615fff', '#16c79a', '#1da9e8', '#f97316', '#ec4899', '#8758f6']
const profileSessionChannelName = 'moulaga:profile-session'
const profileSessionStorageKey = 'moulaga:profile-session-change'
const profileSessionLockedStorageKey = 'moulaga:profile-session-locked'

type ProfileSessionChange = 'selected' | 'locked'

function profileSessionIsLocallyLocked() {
  try {
    return localStorage.getItem(profileSessionLockedStorageKey) === 'true'
  } catch (error) {
    if (!(error instanceof DOMException)) throw error
    console.warn('L’état de verrouillage du profil ne peut pas être lu.', error)
    return false
  }
}

function setProfileSessionLocallyLocked(locked: boolean) {
  try {
    if (locked) localStorage.setItem(profileSessionLockedStorageKey, 'true')
    else localStorage.removeItem(profileSessionLockedStorageKey)
  } catch (error) {
    if (!(error instanceof DOMException)) throw error
    console.warn('L’état de verrouillage du profil ne peut pas être enregistré.', error)
  }
}

export function ProfileGate({
  children,
}: {
  children: (session: { profile: UserProfile; profiles: UserProfile[]; inactivityTimeout: number | null; lock: () => Promise<void>; switchProfile: () => Promise<void>; manageProfiles: () => void }) => React.ReactNode
}) {
  const queryClient = useQueryClient()
  const [manageProfiles, setManageProfiles] = useState(false)
  const [openManagerOnSignIn, setOpenManagerOnSignIn] = useState(false)
  const [showProfilePicker, setShowProfilePicker] = useState(profileSessionIsLocallyLocked)
  const [sessionActionError, setSessionActionError] = useState<unknown>(null)
  const [sessionActionPending, setSessionActionPending] = useState(false)
  const profileSessionChannel = useRef<BroadcastChannel | null>(null)
  const clearProfileIdentityQueries = useCallback(() => {
    queryClient.removeQueries({
      predicate: (query) => String(query.queryKey[0]) !== profileQueryKeys.session[0],
    })
  }, [queryClient])
  const showPicker = useCallback(() => {
    setProfileSessionLocallyLocked(true)
    setShowProfilePicker(true)
    setManageProfiles(false)
    queryClient.setQueryData(profileQueryKeys.session, null)
    clearProfileIdentityQueries()
    void queryClient.prefetchQuery({
      queryKey: profileQueryKeys.publicList,
      queryFn: () => profilesApi.list(),
    }).catch(() => undefined)
  }, [clearProfileIdentityQueries, queryClient])
  const broadcastProfileSessionChange = useCallback((change: ProfileSessionChange) => {
    if (profileSessionChannel.current) {
      profileSessionChannel.current.postMessage(change)
      return
    }
    try {
      localStorage.setItem(
        profileSessionStorageKey,
        `${change}:${crypto.randomUUID()}`,
      )
      localStorage.removeItem(profileSessionStorageKey)
    } catch (error) {
      if (!(error instanceof DOMException)) throw error
      console.warn('La synchronisation de profil entre onglets est indisponible.', error)
    }
  }, [])

  useEffect(() => {
    window.addEventListener('moulaga:profile-session-ended', showPicker)
    return () => window.removeEventListener('moulaga:profile-session-ended', showPicker)
  }, [showPicker])
  useEffect(() => {
    const synchronizeSession = (change: unknown) => {
      advanceProfileSessionGeneration()
      if (change === 'locked') {
        showPicker()
        return
      }
      if (change !== 'selected') return

      setProfileSessionLocallyLocked(false)
      setShowProfilePicker(false)
      setManageProfiles(false)
      queryClient.setQueryData(profileQueryKeys.session, null)
      clearProfileIdentityQueries()
      void queryClient.fetchQuery({
        queryKey: profileQueryKeys.session,
        queryFn: profilesApi.session,
      }).catch(() => showPicker())
    }
    const onStorage = (event: StorageEvent) => {
      if (event.key !== profileSessionStorageKey || event.newValue === null) return
      synchronizeSession(event.newValue.split(':', 1)[0])
    }
    window.addEventListener('storage', onStorage)

    const channel = 'BroadcastChannel' in window
      ? new BroadcastChannel(profileSessionChannelName)
      : null
    profileSessionChannel.current = channel
    if (channel) {
      channel.onmessage = (event: MessageEvent<unknown>) => {
        synchronizeSession(event.data)
      }
    }
    return () => {
      if (profileSessionChannel.current === channel) profileSessionChannel.current = null
      channel?.close()
      window.removeEventListener('storage', onStorage)
    }
  }, [clearProfileIdentityQueries, queryClient, showPicker])
  const session = useQuery({
    queryKey: profileQueryKeys.session,
    queryFn: profilesApi.session,
    retry: false,
  })
  const profileListKey = session.data?.profile.role === 'admin'
    ? profileQueryKeys.adminList
    : profileQueryKeys.publicList
  const profiles = useQuery({
    queryKey: profileListKey,
    queryFn: () => profilesApi.list(session.data?.profile.role === 'admin'),
    retry: false,
    enabled: !session.isPending,
  })

  const endSession = async () => {
    setSessionActionError(null)
    setSessionActionPending(true)
    advanceProfileSessionGeneration()
    showPicker()
    broadcastProfileSessionChange('locked')
    try {
      await profilesApi.lock()
    } catch (error) {
      setSessionActionError(error)
    } finally {
      setSessionActionPending(false)
    }
  }

  if (session.isPending || profiles.isPending) return <div className="profile-loading">Chargement des profils…</div>

  if (session.data && !showProfilePicker) {
    return (
      <>
        {children({
          profile: session.data.profile,
          profiles: profiles.data ?? [],
          inactivityTimeout: session.data.profile.has_pin ? 15 * 60 : null,
          lock: endSession,
          switchProfile: endSession,
          manageProfiles: () => setManageProfiles(true),
        })}
        {sessionActionError && (
          <div className="error-banner" role="alert">
            Impossible de fermer le profil : {errorMessage(sessionActionError)}
          </div>
        )}
        {manageProfiles && (
          <ProfileManager
            activeProfile={session.data.profile}
            profiles={profiles.data ?? []}
            onClose={() => setManageProfiles(false)}
            onChanged={async () => {
              await queryClient.invalidateQueries({ queryKey: profileQueryKeys.listPrefix })
              await queryClient.invalidateQueries({ queryKey: profileQueryKeys.session })
            }}
          />
        )}
      </>
    )
  }

  return (
    <ProfilePicker
      error={profiles.error ?? (session.error instanceof ApiError && session.error.status === 401 ? null : session.error)}
      profiles={profiles.data ?? []}
      onManageRequest={() => setOpenManagerOnSignIn(true)}
      onConnected={async (profileSession) => {
        setSessionActionError(null)
        setProfileSessionLocallyLocked(false)
        setShowProfilePicker(false)
        clearProfileIdentityQueries()
        queryClient.setQueryData(profileQueryKeys.session, profileSession)
        void queryClient.prefetchQuery({
          queryKey: profileSession.profile.role === 'admin'
            ? profileQueryKeys.adminList
            : profileQueryKeys.publicList,
          queryFn: () => profilesApi.list(profileSession.profile.role === 'admin'),
        }).catch(() => undefined)
        broadcastProfileSessionChange('selected')
        if (openManagerOnSignIn) {
          setManageProfiles(true)
          setOpenManagerOnSignIn(false)
        }
      }}
      sessionActionError={sessionActionError}
      sessionActionPending={sessionActionPending}
    />
  )
}

function ProfilePicker({
  profiles,
  error,
  sessionActionError,
  sessionActionPending,
  onManageRequest,
  onConnected,
}: {
  profiles: UserProfile[]
  error: Error | null
  sessionActionError: unknown
  sessionActionPending: boolean
  onManageRequest: () => void
  onConnected: (session: ProfileSession) => Promise<void>
}) {
  const [selected, setSelected] = useState<UserProfile | null>(null)
  const [managementRequested, setManagementRequested] = useState(false)
  const selectionInFlight = useRef(false)
  const [isSelecting, setIsSelecting] = useState(false)
  const open = useMutation({
    mutationFn: ({ profile, pin }: { profile: UserProfile; pin?: string }) => profilesApi.openSession(profile.id, pin),
    onSuccess: onConnected,
  })
  const selectProfile = async (profile: UserProfile, pin?: string) => {
    if (selectionInFlight.current) return
    selectionInFlight.current = true
    setIsSelecting(true)
    try {
      await open.mutateAsync({ profile, pin })
    } finally {
      selectionInFlight.current = false
      setIsSelecting(false)
    }
  }
  const isOnboarding = profiles.length === 0
  const selectionPending = sessionActionPending || isSelecting || open.isPending
  const protectedProfile = selected?.has_pin ? selected : null
  const returnToProfiles = () => {
    setSelected(null)
    open.reset()
  }

  return (
    <main className="profile-picker">
      <section className="profile-picker-card">
        <div className="profile-brand"><span className="brand-mark">M</span><strong>Moulaga</strong></div>
        <p className="eyebrow">
          {isOnboarding ? 'Bienvenue' : protectedProfile ? 'Profil protégé' : 'Qui utilise Moulaga ?'}
        </p>
        <h1>
          {isOnboarding
            ? 'Créez le premier profil'
            : protectedProfile
              ? `Bonjour ${protectedProfile.name}`
              : 'Choisissez votre profil'}
        </h1>
        <p className="profile-picker-copy">
          {isOnboarding
            ? 'Ce premier profil sera administrateur de cette instance.'
            : protectedProfile
              ? 'Saisissez votre code PIN pour accéder à vos données.'
            : 'Vos données restent privées sur cette instance. Aucun accès invité n’est disponible.'}
        </p>
        {error && <p className="form-error">Impossible de charger les profils : {errorMessage(error)}</p>}
        {sessionActionError ? (
          <p className="form-error">
            Le profil est masqué, mais la fermeture de la session distante a échoué : {errorMessage(sessionActionError)}
          </p>
        ) : null}
        {!isOnboarding && !protectedProfile && (
          <div className="profile-tiles" aria-label="Profils disponibles">
            {profiles.filter((profile) => profile.active).map((profile) => (
              <button className="profile-tile" disabled={selectionPending} key={profile.id} type="button" onClick={() => {
                setSelected(profile)
                if (!profile.has_pin) void selectProfile(profile)
              }}>
                <ProfileAvatar profile={profile} />
                <strong>{profile.name}</strong>
                <small>{profile.role === 'admin' ? 'Administrateur' : 'Membre'}</small>
              </button>
            ))}
            <button className="profile-tile profile-add-tile" disabled={selectionPending} type="button" onClick={() => {
              setManagementRequested(true)
              onManageRequest()
            }}>
              <span><Icon name="plus" /></span><strong>Ajouter un profil</strong>
            </button>
          </div>
        )}
        {isOnboarding && (
          <ProfileForm
            firstProfile={isOnboarding}
            selectionPending={selectionPending}
            onSaved={(profile, pin) => {
              return selectProfile(profile, pin)
            }}
          />
        )}
        {protectedProfile && (
          <ProfilePinForm
            error={open.error}
            pending={selectionPending}
            profile={protectedProfile}
            onBack={returnToProfiles}
            onClearError={() => open.reset()}
            onSubmit={(pin) => { void selectProfile(protectedProfile, pin) }}
          />
        )}
        {!protectedProfile && open.error && <p className="form-error">{errorMessage(open.error)}</p>}
        {!isOnboarding && !protectedProfile && (
          <div className="profile-selection-footer">
            <button className="text-button" onClick={() => {
              setManagementRequested(true)
              onManageRequest()
            }} type="button">Gérer les profils</button>
            <p className="profile-management-hint">{managementRequested ? 'Choisissez un profil administrateur pour continuer.' : 'La gestion est réservée à un administrateur.'}</p>
          </div>
        )}
      </section>
    </main>
  )
}

function ProfilePinForm({
  profile,
  pending,
  error,
  onBack,
  onClearError,
  onSubmit,
}: {
  profile: UserProfile
  pending: boolean
  error: Error | null
  onBack: () => void
  onClearError: () => void
  onSubmit: (pin: string) => void
}) {
  const [pin, setPin] = useState('')

  return (
    <form className="profile-pin-form" onSubmit={(event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      onSubmit(pin)
    }}>
      <div className="profile-pin-identity">
        <ProfileAvatar profile={profile} />
        <div>
          <strong>{profile.name}</strong>
          <span>{profile.role === 'admin' ? 'Administrateur' : 'Membre'}</span>
        </div>
      </div>
      <PinKeypad
        disabled={pending}
        label={`Code PIN de ${profile.name}`}
        value={pin}
        onChange={(value) => {
          setPin(value)
          if (error) onClearError()
        }}
      />
      {error && <p className="form-error" role="alert">{errorMessage(error)}</p>}
      <div className="profile-pin-actions">
        <button className="text-button" onClick={onBack} type="button">
          <Icon name="back" /> Retour
        </button>
        <button className="primary-button" disabled={pending || pin.length < 4} type="submit">
          {pending ? 'Ouverture…' : 'Ouvrir le profil'} <Icon name="arrow" />
        </button>
      </div>
    </form>
  )
}

function ProfileForm({
  firstProfile,
  onCancel,
  onSaved,
  selectionPending = false,
}: {
  firstProfile: boolean
  onCancel?: () => void
  onSaved: (profile: UserProfile, pin?: string) => Promise<void>
  selectionPending?: boolean
}) {
  const [name, setName] = useState('')
  const [color, setColor] = useState(profileColors[0])
  const [avatar, setAvatar] = useState('')
  const [pin, setPin] = useState('')
  const [configurePin, setConfigurePin] = useState(false)
  const create = useMutation({
    mutationFn: () => profilesApi.create({
      name,
      color,
      avatar: avatar.trim() || null,
      ...(firstProfile && pin ? { pin } : {}),
    }),
    onSuccess: (profile) => onSaved(profile, firstProfile && pin ? pin : undefined),
  })
  return (
    <form className="profile-create-form" onSubmit={(event: FormEvent) => { event.preventDefault(); create.mutate() }}>
      <label>Nom<input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} required /></label>
      <label>Initiale ou avatar<input value={avatar} maxLength={4} onChange={(event) => setAvatar(event.target.value)} placeholder="Facultatif" /></label>
      <label>Couleur<input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label>
      {firstProfile && (
        <div className="profile-onboarding-pin">
          <div>
            <span>
              <strong>PIN facultatif</strong>
              <small>Vous pourrez aussi le configurer plus tard depuis la page Famille.</small>
            </span>
            <button
              className="secondary-button small-button"
              onClick={() => {
                setConfigurePin((current) => !current)
                setPin('')
              }}
              type="button"
            >
              {configurePin ? 'Ne pas utiliser de PIN' : 'Ajouter un PIN'}
            </button>
          </div>
          {configurePin && <PinKeypad label="PIN du premier profil" onChange={setPin} value={pin} />}
        </div>
      )}
      <p>
        {firstProfile
          ? 'Vous pourrez modifier ou retirer ce PIN depuis la page Famille.'
          : 'Ce membre configurera lui-même son PIN depuis son profil.'}
      </p>
      <div>
        {onCancel && <button className="text-button" onClick={onCancel} type="button">Annuler</button>}
        <button
          className="primary-button"
          disabled={create.isPending || selectionPending || (configurePin && pin.length < 4)}
          type="submit"
        >
          {create.isPending ? 'Création…' : firstProfile ? 'Commencer' : 'Créer le profil'}
        </button>
      </div>
      {create.error && <p className="form-error">{errorMessage(create.error)}</p>}
    </form>
  )
}

function ProfileManager({
  activeProfile,
  profiles,
  onClose,
  onChanged,
}: {
  activeProfile: UserProfile
  profiles: UserProfile[]
  onClose: () => void
  onChanged: () => Promise<void>
}) {
  const [editing, setEditing] = useState<UserProfile | null>(null)
  const [creating, setCreating] = useState(false)
  const activeProfiles = useMemo(() => profiles.filter((profile) => profile.active), [profiles])
  if (activeProfile.role !== 'admin') return null
  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-modal="true" className="modal-card profile-manager" role="dialog">
        <div className="modal-header"><div><h2>Gérer les profils</h2><p>Archivez un profil uniquement après avoir résolu ses ressources.</p></div><button aria-label="Fermer" className="icon-action" onClick={onClose} type="button"><Icon name="close" /></button></div>
        <div className="profile-manager-list">
          {profiles.map((profile) => (
            <div key={profile.id}>
              <ProfileAvatar profile={profile} /><span><strong>{profile.name}</strong><small>{profile.role === 'admin' ? 'Administrateur' : 'Membre'}{profile.active ? '' : ' · Archivé'}</small></span>
              <button className="text-button" onClick={() => setEditing(profile)} type="button">Modifier</button>
            </div>
          ))}
          <button className="profile-tile profile-add-tile" onClick={() => setCreating(true)} type="button">
            <span><Icon name="plus" /></span><strong>Ajouter un profil</strong>
          </button>
        </div>
        {creating && <ProfileForm firstProfile={false} onCancel={() => setCreating(false)} onSaved={async () => { await onChanged(); setCreating(false) }} />}
        {editing && (
          <ProfileEditForm
            canArchive={activeProfiles.length > 1}
            canResetPin={editing.id !== activeProfile.id && editing.has_pin}
            profile={editing}
            onChanged={onChanged}
            onClose={() => setEditing(null)}
          />
        )}
      </section>
    </div>
  )
}

function ProfileEditForm({
  profile,
  canArchive,
  canResetPin,
  onClose,
  onChanged,
}: {
  profile: UserProfile
  canArchive: boolean
  canResetPin: boolean
  onClose: () => void
  onChanged: () => Promise<void>
}) {
  const [name, setName] = useState(profile.name)
  const [color, setColor] = useState(profile.color)
  const [avatar, setAvatar] = useState(profile.avatar ?? '')
  const update = useMutation({
    mutationFn: () => profilesApi.update(profile.id, {
      name,
      color,
      avatar: avatar.trim() || null,
      active: profile.active ? undefined : true,
    }),
    onSuccess: async () => { await onChanged(); onClose() },
  })
  const archive = useMutation({
    mutationFn: () => profilesApi.update(profile.id, { active: false }),
    onSuccess: async () => { await onChanged(); onClose() },
  })
  const resetPin = useMutation({
    mutationFn: () => profilesApi.update(profile.id, { pin: null }),
    onSuccess: async () => { await onChanged(); onClose() },
  })
  return <form className="profile-edit-form" onSubmit={(event: FormEvent) => { event.preventDefault(); update.mutate() }}>
    <h3>Modifier {profile.name}</h3>
    <label>Nom<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
    <label>Initiale ou avatar<input maxLength={4} value={avatar} onChange={(event) => setAvatar(event.target.value)} /></label>
    <label>Couleur<input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label>
    {canResetPin && (
      <div className="profile-admin-pin-reset">
        <span><strong>PIN actif</strong><small>Le membre devra en créer un nouveau après sa suppression.</small></span>
        <button
          className="text-button destructive-button"
          disabled={resetPin.isPending}
          onClick={() => {
            if (window.confirm(`Supprimer le PIN de ${profile.name} ?`)) resetPin.mutate()
          }}
          type="button"
        >
          Supprimer le PIN
        </button>
      </div>
    )}
    {profile.active && <p className="modal-hint">Les ressources personnelles de ce profil devront être transférées avant son archivage.</p>}
    <div><button className="text-button" onClick={onClose} type="button">Annuler</button><button className="primary-button" disabled={update.isPending} type="submit">Enregistrer</button>{profile.active && canArchive && <button className="text-button destructive-button" disabled={archive.isPending} onClick={() => archive.mutate()} type="button">Archiver</button>}</div>
    {(update.error || archive.error || resetPin.error) && <p className="form-error">{errorMessage(update.error ?? archive.error ?? resetPin.error)}</p>}
  </form>
}

function ProfileAvatar({ profile }: { profile: Pick<UserProfile, 'name' | 'avatar' | 'color'> }) {
  return <span className="profile-avatar" style={{ background: profile.color }}>{profile.avatar || profile.name.slice(0, 1).toUpperCase()}</span>
}
