import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
  maxWidth?: number;
  disabled?: boolean;
  placement?: 'top' | 'right';
}

interface TooltipPosition {
  left: number;
  top: number;
  transform: string;
  arrowClassName: string;
}

export function Tooltip({
  content,
  children,
  className,
  maxWidth = 320,
  disabled = false,
  placement = 'top',
}: TooltipProps) {
  const triggerRef = useRef<HTMLSpanElement | null>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<TooltipPosition | null>(null);

  const updatePosition = useCallback(() => {
    const node = triggerRef.current;
    if (!node) return;

    const rect = node.getBoundingClientRect();
    const viewportPadding = 12;
    const tooltipWidth = Math.min(maxWidth, window.innerWidth - viewportPadding * 2);
    if (placement === 'right') {
      const tooltipHeightEstimate = 44;
      const centeredTop = rect.top + rect.height / 2;
      const clampedTop = Math.min(
        window.innerHeight - viewportPadding - tooltipHeightEstimate / 2,
        Math.max(viewportPadding + tooltipHeightEstimate / 2, centeredTop),
      );

      setPosition({
        left: rect.right + 10,
        top: clampedTop,
        transform: 'translate(0, -50%)',
        arrowClassName: 'qalens-tooltip-arrow qalens-tooltip-arrow-right',
      });
      return;
    }

    const centeredLeft = rect.left + rect.width / 2;
    const clampedLeft = Math.min(
      window.innerWidth - viewportPadding - tooltipWidth / 2,
      Math.max(viewportPadding + tooltipWidth / 2, centeredLeft),
    );

    setPosition({
      left: clampedLeft,
      top: rect.top - 10,
      transform: 'translate(-50%, -100%)',
      arrowClassName: 'qalens-tooltip-arrow',
    });
  }, [maxWidth, placement]);

  useEffect(() => {
    if (!open || disabled) return;

    updatePosition();

    const handleReposition = () => updatePosition();
    window.addEventListener('scroll', handleReposition, true);
    window.addEventListener('resize', handleReposition);

    return () => {
      window.removeEventListener('scroll', handleReposition, true);
      window.removeEventListener('resize', handleReposition);
    };
  }, [open, updatePosition]);

  return (
    <>
      <span
        ref={triggerRef}
        className={className}
        onMouseEnter={disabled ? undefined : () => setOpen(true)}
        onMouseLeave={disabled ? undefined : () => setOpen(false)}
        onFocus={disabled ? undefined : () => setOpen(true)}
        onBlur={disabled ? undefined : () => setOpen(false)}
      >
        {children}
      </span>

      {!disabled && open && position && createPortal(
        <div
          className="qalens-tooltip"
          style={{
            left: position.left,
            top: position.top,
            maxWidth,
            transform: position.transform,
          }}
          role="tooltip"
        >
          {content}
          <span className={position.arrowClassName} aria-hidden="true" />
        </div>,
        document.body,
      )}
    </>
  );
}
