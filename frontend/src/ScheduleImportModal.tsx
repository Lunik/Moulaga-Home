import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'

import { apiPost } from './api/client'
import {
  Field,
  FormTextarea,
  Modal,
  errorMessage,
} from './ui'

export function ScheduleImportModal({
  title,
  description,
  endpoint,
  amountLabel,
  ariaLabel,
  placeholder,
  onClose,
  onSaved,
}: {
  title: string
  description: string
  endpoint: string
  amountLabel: string
  ariaLabel: string
  placeholder: string
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const [content, setContent] = useState('')
  const mutation = useMutation({
    mutationFn: () => apiPost(endpoint, { content }),
    onSuccess: onSaved,
  })
  const formId = `schedule-import-${endpoint.replaceAll('/', '-')}`

  return (
    <Modal
      title={title}
      description={description}
      onClose={onClose}
      actions={(
        <>
          <button
            className="primary-button"
            type="submit"
            form={formId}
            disabled={!content.trim() || mutation.isPending}
          >
            {mutation.isPending ? 'Import…' : 'Importer'}
          </button>
          <button className="text-button" type="button" onClick={onClose}>Annuler</button>
        </>
      )}
    >
      <form
        className="snapshot-import-form"
        id={formId}
        onSubmit={(event) => {
          event.preventDefault()
          mutation.mutate()
        }}
      >
        <div className="snapshot-import-format">
          <strong>Format TSV</strong>
          <code>DD/MM/YYYY ↹ {amountLabel}</code>
        </div>
        <Field label="Données à importer">
          <FormTextarea
            aria-label={ariaLabel}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder={placeholder}
            rows={8}
            spellCheck={false}
            required
          />
        </Field>
        <p className="modal-hint">
          L’en-tête « Date ↹ Montant » est facultative. Le suffixe € est accepté.
          Les dates déjà enregistrées seront remplacées. En cas d’erreur, aucune
          ligne ne sera importée.
        </p>
        {mutation.error && <p className="form-error">{errorMessage(mutation.error)}</p>}
      </form>
    </Modal>
  )
}
