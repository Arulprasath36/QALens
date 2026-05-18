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
    <div className="qalens-modal-root" role="dialog" aria-modal="true" aria-label={title}>
      <button
        type="button"
        aria-label="Close modal"
        className="qalens-modal-backdrop"
        onClick={onClose}
      />

      <div className={`qalens-modal-panel ${widthClassName}`}>
        <div className="qalens-modal-header">
          <div className="min-w-0">
            <h2 className="qalens-modal-title">{title}</h2>
            {meta && <div className="qalens-modal-meta">{meta}</div>}
          </div>
          <button type="button" onClick={onClose} className="qalens-chip type-chip">
            Close
          </button>
        </div>

        <div className="qalens-modal-body">{children}</div>

        {footer && <div className="qalens-modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
