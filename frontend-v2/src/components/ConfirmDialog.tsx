interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  dangerous?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  dangerous = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null;

  return (
    <div
      className="dialog-backdrop"
      role="dialog"
      aria-modal
      aria-labelledby="dialog-title"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div className="dialog-box">
        <p className="dialog-title" id="dialog-title">{title}</p>
        <p className="dialog-message">{message}</p>
        <div className="dialog-actions">
          <button className="btn" onClick={onCancel}>{cancelLabel}</button>
          <button
            className={`btn ${dangerous ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
