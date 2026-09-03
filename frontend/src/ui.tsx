import type { CSSProperties, ReactNode } from 'react'

import type { MerchantIdentity } from './api/types'

export type IconName =
  | 'accounts'
  | 'alert'
  | 'arrow'
  | 'back'
  | 'budget'
  | 'calendar'
  | 'check'
  | 'close'
  | 'database'
  | 'debt'
  | 'edit'
  | 'family'
  | 'grid'
  | 'holdings'
  | 'plus'
  | 'receipt'
  | 'recurring'
  | 'refresh'
  | 'rules'
  | 'search'
  | 'settings'
  | 'sparkle'
  | 'target'
  | 'trash'
  | 'trend'
  | 'wealth'

export function Icon({ name, className }: { name: IconName; className?: string }) {
  const paths: Record<IconName, ReactNode> = {
    accounts: (
      <>
        <path d="M4 6.5h13a3 3 0 0 1 3 3v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 2 17.5v-11A2.5 2.5 0 0 1 4.5 4H17" />
        <path d="M16 12h6v4h-6a2 2 0 0 1 0-4Z" />
      </>
    ),
    alert: (
      <>
        <path d="M12 3 2.5 20h19L12 3Z" />
        <path d="M12 9v4M12 17h.01" />
      </>
    ),
    arrow: <path d="m9 18 6-6-6-6" />,
    back: <path d="m15 18-6-6 6-6" />,
    budget: (
      <>
        <path d="M4 5h16v14H4z" />
        <path d="M16 10h6v4h-6a2 2 0 0 1 0-4Z" />
      </>
    ),
    calendar: (
      <>
        <rect x="3" y="5" width="18" height="16" rx="2" />
        <path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01" />
      </>
    ),
    check: <path d="m5 12 4 4L19 6" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    database: (
      <>
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
      </>
    ),
    debt: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M8 9h8M8 15h8M10 7v10" />
      </>
    ),
    edit: (
      <>
        <path d="m4 20 4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20Z" />
        <path d="m14 7 3 3" />
      </>
    ),
    family: (
      <>
        <circle cx="9" cy="8" r="3" />
        <circle cx="17" cy="9" r="2.5" />
        <path d="M3 20v-2a5 5 0 0 1 10 0v2M14 15a4.5 4.5 0 0 1 7 3.7V20" />
      </>
    ),
    grid: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </>
    ),
    holdings: (
      <>
        <path d="M4 19V9M10 19V5M16 19v-7M22 19V3" />
        <path d="M2 19h22" />
      </>
    ),
    plus: <path d="M12 5v14M5 12h14" />,
    receipt: (
      <>
        <path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2V3Z" />
        <path d="M9 8h6M9 12h6M9 16h4" />
      </>
    ),
    recurring: (
      <>
        <path d="M20 7h-7a6 6 0 0 0-6 6v1" />
        <path d="m17 4 3 3-3 3M4 17h7a6 6 0 0 0 6-6v-1M7 20l-3-3 3-3" />
      </>
    ),
    refresh: (
      <>
        <path d="M20 11a8 8 0 1 0-2.3 5.7" />
        <path d="M20 4v7h-7" />
      </>
    ),
    rules: (
      <>
        <path d="M4 6h16M4 12h10M4 18h16" />
        <circle cx="17" cy="12" r="2" />
      </>
    ),
    search: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </>
    ),
    settings: (
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" />
      </>
    ),
    sparkle: <path d="m12 3 1.5 5.5L19 10l-5.5 1.5L12 17l-1.5-5.5L5 10l5.5-1.5L12 3ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" />,
    target: (
      <>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1" />
      </>
    ),
    trash: (
      <>
        <path d="M4 7h16M9 7V4h6v3M7 7l1 14h8l1-14M10 11v6M14 11v6" />
      </>
    ),
    trend: (
      <>
        <path d="m3 17 6-6 4 4 8-9" />
        <path d="M15 6h6v6" />
      </>
    ),
    wealth: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10M15 9.5c0-1.4-1.3-2.5-3-2.5S9 8 9 9.4c0 3.2 6 1.4 6 4.4 0 1.3-1.3 2.2-3 2.2s-3-1-3-2.4" />
      </>
    ),
  }

  return (
    <svg
      aria-hidden="true"
      className={className ? `app-icon ${className}` : 'app-icon'}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  )
}

export function Panel({
  title,
  subtitle,
  action,
  children,
  className = '',
}: {
  title: string
  subtitle?: string
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header split-header">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  )
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  )
}

export function EmptyState({
  icon = 'database',
  title,
  text,
  action,
}: {
  icon?: IconName
  title?: string
  text: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <span><Icon name={icon} /></span>
      {title && <strong>{title}</strong>}
      <p>{text}</p>
      {action}
    </div>
  )
}

export function StatusBadge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'positive' | 'negative' | 'warning' | 'primary'
}) {
  return <span className={`status-badge ${tone}`}>{children}</span>
}

export function MerchantAvatar({
  description,
  identities,
}: {
  description: string
  identities?: MerchantIdentity[]
}) {
  const normalized = description.toLocaleLowerCase('fr-FR')
  const identity = identities?.find((item) => normalized.includes(item.pattern.toLocaleLowerCase('fr-FR')))
  return (
    <span
      className="transaction-avatar"
      style={identity ? { background: identity.color, color: '#fff' } : undefined}
      title={identity?.label}
    >
      {identity?.monogram || initials(description)}
    </span>
  )
}

export function ProgressBar({
  value,
  color,
  danger = false,
}: {
  value: number
  color?: string
  danger?: boolean
}) {
  const width = Math.min(100, Math.max(0, value))
  const style: CSSProperties | undefined = color && !danger ? { width: `${width}%`, background: color } : { width: `${width}%` }
  return (
    <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)}>
      <span className={danger ? 'danger' : ''} style={style} />
    </div>
  )
}

export const chartTooltipStyle: CSSProperties = {
  background: 'var(--surface-raised)',
  border: '1px solid var(--line-strong)',
  borderRadius: '12px',
  color: 'var(--text)',
}

let activeLocale = 'fr-FR'
let activeDateFormat: 'localized' | 'day-month-year' | 'YYYY-MM-DD' = 'localized'

export function configureUiPreferences(
  language: 'fr' | 'en' | 'de' | 'es' = 'fr',
  dateFormat: 'localized' | 'day-month-year' | 'YYYY-MM-DD' = 'localized',
) {
  activeLocale = { fr: 'fr-FR', en: 'en-GB', de: 'de-DE', es: 'es-ES' }[language]
  activeDateFormat = dateFormat
}

export function money(value: string | number | undefined | null): string {
  return new Intl.NumberFormat(activeLocale, { style: 'currency', currency: 'EUR' }).format(Number(value ?? 0))
}

export function signedMoney(value: string | number): string {
  const amount = Number(value)
  if (amount === 0) return money(0)
  return `${amount > 0 ? '+' : '−'}${money(Math.abs(amount))}`
}

export function compactMoney(value: number): string {
  const absolute = Math.abs(value)
  if (absolute >= 1_000_000) return `${(value / 1_000_000).toLocaleString(activeLocale, { maximumFractionDigits: 1 })} M`
  if (absolute >= 1_000) return `${(value / 1_000).toLocaleString(activeLocale, { maximumFractionDigits: 1 })} k`
  return new Intl.NumberFormat(activeLocale).format(value)
}

export function formatDate(value: string | null | undefined): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return 'Date invalide'
  if (activeDateFormat === 'YYYY-MM-DD') return value
  const [year, month, day] = value.split('-').map(Number)
  if (activeDateFormat === 'day-month-year') {
    return `${String(day).padStart(2, '0')}-${String(month).padStart(2, '0')}-${year}`
  }
  return new Intl.DateTimeFormat(activeLocale, { day: '2-digit', month: 'short', year: 'numeric' }).format(
    new Date(year, month - 1, day),
  )
}

export function formatMonth(value: string | null | undefined): string {
  if (!value || !/^\d{4}-\d{2}$/.test(value)) return 'Période invalide'
  const [year, month] = value.split('-').map(Number)
  return new Intl.DateTimeFormat(activeLocale, { month: 'long', year: 'numeric' }).format(new Date(year, month - 1, 1))
}

export function shortMonth(value: string | null | undefined): string {
  if (!value || !/^\d{4}-\d{2}$/.test(value)) return '—'
  const [year, month] = value.split('-').map(Number)
  return new Intl.DateTimeFormat(activeLocale, { month: 'short' }).format(new Date(year, month - 1, 1))
}

export function localDateInputValue(): string {
  const now = new Date()
  const localTime = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
  return localTime.toISOString().slice(0, 10)
}

export function longToday(): string {
  const formatted = new Intl.DateTimeFormat(activeLocale, {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date())
  return formatted.charAt(0).toUpperCase() + formatted.slice(1)
}

export function initials(value: string): string {
  const words = value.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '—'
  return words.slice(0, 2).map((word) => word[0]).join('').toLocaleUpperCase('fr-FR')
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Une erreur inattendue est survenue.'
}
