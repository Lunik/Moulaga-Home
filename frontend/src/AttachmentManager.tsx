import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiUpload } from './api/client'
import type { StoredAttachment } from './api/types'
import { FormInput, Icon, errorMessage, formatFileSize } from './ui'

export type AttachmentOwner =
  | { kind: 'snapshot'; accountId: number; snapshotId: number }
  | { kind: 'recurring'; seriesId: number }
  | { kind: 'debt'; debtId: number }
  | { kind: 'real-estate'; assetId: number }
  | { kind: 'payslip'; payslipId: number }

interface AttachmentConfig {
  resourcePath: string
  attachmentQueryKey: readonly unknown[]
  parentQueryKeys: readonly (readonly unknown[])[]
}

function attachmentConfig(owner: AttachmentOwner): AttachmentConfig {
  switch (owner.kind) {
    case 'snapshot':
      return {
        resourcePath: `/accounts/${owner.accountId}/snapshots/${owner.snapshotId}`,
        attachmentQueryKey: ['snapshot-attachments', owner.accountId, owner.snapshotId],
        parentQueryKeys: [['account-snapshots', owner.accountId]],
      }
    case 'recurring':
      return {
        resourcePath: `/recurring/${owner.seriesId}`,
        attachmentQueryKey: ['recurring-attachments', owner.seriesId],
        parentQueryKeys: [['recurring-series']],
      }
    case 'debt':
      return {
        resourcePath: `/debts/${owner.debtId}`,
        attachmentQueryKey: ['debt-attachments', owner.debtId],
        parentQueryKeys: [['debts']],
      }
    case 'real-estate':
      return {
        resourcePath: `/real-estate/${owner.assetId}`,
        attachmentQueryKey: ['real-estate-attachments', owner.assetId],
        parentQueryKeys: [['real-estate']],
      }
    case 'payslip':
      return {
        resourcePath: `/work/payslips/${owner.payslipId}`,
        attachmentQueryKey: ['work-payslip-attachments', owner.payslipId],
        parentQueryKeys: [['work-payslips']],
      }
  }
}

export function AttachmentManager({
  owner,
  readOnly,
  onChanged,
}: {
  owner: AttachmentOwner
  readOnly: boolean
  onChanged?: () => Promise<unknown> | void
}) {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [inputKey, setInputKey] = useState(0)
  const { resourcePath, attachmentQueryKey, parentQueryKeys } = attachmentConfig(owner)
  const attachments = useQuery({
    queryKey: attachmentQueryKey,
    queryFn: () => apiGet<StoredAttachment[]>(`${resourcePath}/attachments`),
  })
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: attachmentQueryKey }),
      ...parentQueryKeys.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    ])
    await onChanged?.()
  }
  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('Choisissez un fichier à joindre.')
      const data = new FormData()
      data.append('file', file)
      return apiUpload<StoredAttachment>(`${resourcePath}/attachments`, data)
    },
    onSuccess: async () => {
      setFile(null)
      setInputKey((current) => current + 1)
      await refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (attachmentId: number) => apiDelete(
      `${resourcePath}/attachments/${attachmentId}`,
    ),
    onSuccess: refresh,
  })
  return (
    <div className="attachment-manager">
      <div className="attachment-heading">
        <span>
          <strong>Pièces jointes</strong>
          <small>Stockage local, 25 Mio maximum par fichier.</small>
        </span>
        {!readOnly && (
          <form
            className="attachment-upload"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              upload.mutate()
            }}
          >
            <FormInput
              key={inputKey}
              aria-label="Choisir une pièce jointe"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <button className="secondary-button small-button" type="submit" disabled={!file || upload.isPending}>
              <Icon name="attachment" />{upload.isPending ? 'Ajout…' : 'Joindre'}
            </button>
          </form>
        )}
      </div>
      {attachments.isLoading ? (
        <p className="attachment-empty">Chargement…</p>
      ) : (attachments.data ?? []).length > 0 ? (
        <div className="attachment-list">
          {attachments.data?.map((attachment) => (
            <div key={attachment.id}>
              <Icon name="attachment" />
              <span>
                <a href={`/api${resourcePath}/attachments/${attachment.id}/download`}>
                  {attachment.original_name}
                </a>
                <small>{formatFileSize(attachment.size)}</small>
              </span>
              {!readOnly && (
                <button
                  className="icon-action destructive-button"
                  type="button"
                  aria-label={`Supprimer ${attachment.original_name}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(attachment.id)}
                >
                  <Icon name="trash" />
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <p className="attachment-empty">Aucune pièce jointe.</p>
      )}
      {(attachments.error || upload.error || remove.error) && (
        <p className="form-error">{errorMessage(attachments.error ?? upload.error ?? remove.error)}</p>
      )}
    </div>
  )
}
