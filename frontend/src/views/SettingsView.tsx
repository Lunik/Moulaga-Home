import { FormEvent, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPatch } from '../api/client'
import type { AppSettings } from '../api/types'
import { FormInput, Icon, Panel, errorMessage, formatDate } from '../ui'

export function SettingsView() {
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiGet<AppSettings>('/preferences'),
  })
  const update = useMutation({
    mutationFn: (payload: Partial<AppSettings>) => apiPatch<AppSettings>('/preferences', payload),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['settings'] }),
        queryClient.invalidateQueries({ queryKey: ['budget-overview'] }),
        queryClient.invalidateQueries({ queryKey: ['budget-cashflow'] }),
        queryClient.invalidateQueries({ queryKey: ['budget-spending'] }),
      ])
    },
  })

  if (settings.isLoading) return <div className="loading-card">Chargement des paramètres…</div>
  if (settings.error) return <div className="error-banner">{errorMessage(settings.error)}</div>
  if (!settings.data) return null

  return (
    <div className="view-stack settings-stack">
      {update.error && <div className="error-banner">{errorMessage(update.error)}</div>}
      <AppearanceSettings settings={settings.data} onSave={(payload) => update.mutate(payload)} />
      <BudgetCycleSettings
        settings={settings.data}
        saving={update.isPending}
        onSave={(payload) => update.mutate(payload)}
      />
    </div>
  )
}

function AppearanceSettings({
  settings,
  onSave,
}: {
  settings: AppSettings
  onSave: (payload: Partial<AppSettings>) => void
}) {
  return (
    <Panel title="Apparence" subtitle="Personnalisez uniquement la présentation de cette instance.">
      <div className="setting-list">
        <SettingRow label="Thème">
          <SegmentedControl
            value={settings.theme}
            options={[
              ['light', 'Clair'],
              ['dark', 'Sombre'],
              ['system', 'Système'],
            ]}
            onChange={(value) => onSave({ theme: value as AppSettings['theme'] })}
          />
        </SettingRow>
        <SettingRow label="Langue">
          <SegmentedControl
            value={settings.language}
            options={[
              ['fr', 'FR'],
              ['en', 'EN'],
              ['de', 'DE'],
              ['es', 'ES'],
            ]}
            onChange={(value) => onSave({ language: value as AppSettings['language'] })}
          />
        </SettingRow>
        <SettingRow label="Format de date">
          <SegmentedControl
            value={settings.date_format}
            options={[
              ['localized', 'Localisé'],
              ['day-month-year', 'JJ-MM-AAAA'],
              ['YYYY-MM-DD', 'AAAA-MM-JJ'],
            ]}
            onChange={(value) => onSave({ date_format: value as AppSettings['date_format'] })}
          />
        </SettingRow>
        <SettingRow label="Style de navigation">
          <SegmentedControl
            value={settings.navigation_style}
            options={[
              ['sidebar', 'Actuel'],
              ['compact', 'Compact'],
              ['topbar', 'Barre haute'],
            ]}
            onChange={(value) => onSave({ navigation_style: value as AppSettings['navigation_style'] })}
          />
        </SettingRow>
      </div>
    </Panel>
  )
}

function BudgetCycleSettings({
  settings,
  saving,
  onSave,
}: {
  settings: AppSettings
  saving: boolean
  onSave: (payload: Partial<AppSettings>) => void
}) {
  const [day, setDay] = useState(String(settings.budget_cycle_start_day))
  useEffect(() => setDay(String(settings.budget_cycle_start_day)), [settings.budget_cycle_start_day])
  const bounds = cycleBounds(settings.budget_cycle_start_day)

  return (
    <Panel
      title="Jour de paie"
      subtitle="Votre cycle budgétaire démarre ce jour-là chaque mois, pas forcément le 1er."
    >
      <form
        className="cycle-form"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          onSave({ budget_cycle_start_day: Number(day) })
        }}
      >
        <label>
          <span>Jour de début du cycle</span>
          <FormInput
            type="number"
            min="1"
            max="28"
            value={day}
            onChange={(event) => setDay(event.target.value)}
            required
          />
        </label>
        <button className="primary-button" type="submit" disabled={saving}>
          Enregistrer
        </button>
      </form>
      <p className="setting-hint">
        <Icon name="calendar" /> Cycle en cours : du {formatDate(bounds.start)} au{' '}
        {formatDate(bounds.end)}
      </p>
    </Panel>
  )
}

function SettingRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="setting-row">
      <strong>{label}</strong>
      {children}
    </div>
  )
}

function SegmentedControl({
  value,
  options,
  onChange,
}: {
  value: string
  options: Array<[string, string]>
  onChange: (value: string) => void
}) {
  return (
    <div className="segmented-control">
      {options.map(([option, label]) => (
        <button
          className={value === option ? 'active' : ''}
          type="button"
          key={option}
          onClick={() => onChange(option)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function cycleBounds(startDay: number): { start: string; end: string } {
  const today = new Date()
  const start = new Date(today.getFullYear(), today.getMonth(), startDay)
  if (today.getDate() < startDay) start.setMonth(start.getMonth() - 1)
  const end = new Date(start.getFullYear(), start.getMonth() + 1, startDay - 1)
  return { start: localIsoDate(start), end: localIsoDate(end) }
}

function localIsoDate(date: Date): string {
  const adjusted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return adjusted.toISOString().slice(0, 10)
}
