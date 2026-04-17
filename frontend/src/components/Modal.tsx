import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface ModalProps {
  open: boolean;
  title: string;
  meta?: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  widthClassName?: string;
}

export function Modal({
  open,
  title,
  meta,
  footer,
  onClose,
  children,
  widthClassName = 'max-w-4xl',
}: ModalProps) {
  useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="qara-modal-root" role="dialog" aria-modal="true" aria-label={title}>
      <button
        type="button"
        aria-label="Close modal"
        className="qara-modal-backdrop"
        onClick={onClose}
      />

      <div className={`qara-modal-panel ${widthClassName}`}>
        <div className="qara-modal-header">
          <div className="min-w-0">
            <h2 className="qara-modal-title">{title}</h2>
            {meta && <div className="qara-modal-meta">{meta}</div>}
          </div>
          <button type="button" onClick={onClose} className="qara-chip type-chip">
            Close
          </button>
        </div>

        <div className="qara-modal-body">{children}</div>

        {footer && <div className="qara-modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
