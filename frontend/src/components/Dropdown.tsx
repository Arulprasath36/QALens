import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';

export interface DropdownOption<T extends string = string> {
  value: T;
  label: string;
  disabled?: boolean;
}

interface DropdownProps<T extends string = string> {
  value: T;
  onChange: (value: T) => void;
  options: DropdownOption<T>[];
  placeholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
  optionClassName?: string;
  leftIcon?: ReactNode;
  renderValue?: (option: DropdownOption<T> | undefined) => ReactNode;
  align?: 'left' | 'right';
  fullWidth?: boolean;
  hideChevron?: boolean;
}

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function Dropdown<T extends string = string>({
  value,
  onChange,
  options,
  placeholder,
  ariaLabel,
  disabled = false,
  className,
  triggerClassName,
  menuClassName,
  optionClassName,
  leftIcon,
  renderValue,
  align = 'left',
  fullWidth = false,
  hideChevron = false,
}: DropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const listboxId = useId();

  const enabledOptions = useMemo(
    () => options.filter(option => !option.disabled),
    [options],
  );

  const selectedOption = options.find(option => option.value === value);

  useEffect(() => {
    if (!open) return;

    const selectedEnabledIndex = enabledOptions.findIndex(option => option.value === value);
    setActiveIndex(selectedEnabledIndex >= 0 ? selectedEnabledIndex : 0);
  }, [enabledOptions, open, value]);

  useEffect(() => {
    if (!open || activeIndex < 0) return;

    optionRefs.current[activeIndex]?.focus();
  }, [activeIndex, open]);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }

    function handleWindowBlur() {
      setOpen(false);
    }

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('blur', handleWindowBlur);

    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('blur', handleWindowBlur);
    };
  }, [open]);

  function commit(nextValue: T) {
    onChange(nextValue);
    setOpen(false);
    buttonRef.current?.focus();
  }

  function moveActive(delta: number) {
    if (enabledOptions.length === 0) return;

    setActiveIndex(current => {
      const base = current < 0 ? 0 : current;
      return (base + delta + enabledOptions.length) % enabledOptions.length;
    });
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (disabled) return;

    if (!open) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        setOpen(true);
      }
      return;
    }

    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
      return;
    }

    if (event.key === 'Tab') {
      setOpen(false);
      return;
    }

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      moveActive(1);
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveActive(-1);
      return;
    }

    if (event.key === 'Home') {
      event.preventDefault();
      setActiveIndex(0);
      return;
    }

    if (event.key === 'End') {
      event.preventDefault();
      setActiveIndex(enabledOptions.length - 1);
      return;
    }

    if ((event.key === 'Enter' || event.key === ' ') && activeIndex >= 0) {
      event.preventDefault();
      const nextOption = enabledOptions[activeIndex];
      if (nextOption) commit(nextOption.value);
    }
  }

  return (
    <div
      ref={rootRef}
      className={cx('relative', fullWidth && 'w-full', className)}
      onKeyDown={handleKeyDown}
    >
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => setOpen(current => !current)}
        className={cx(
          'qara-control qara-dropdown-trigger',
          fullWidth && 'w-full',
          disabled && 'cursor-not-allowed opacity-50',
          triggerClassName,
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          {leftIcon && <span className="shrink-0 text-muted">{leftIcon}</span>}
          <span className="truncate">
            {renderValue
              ? renderValue(selectedOption)
              : selectedOption?.label ?? placeholder ?? ''}
          </span>
        </span>
        {!hideChevron && (
          <span className={cx('qara-dropdown-chevron', open && 'rotate-180')}>
            <svg viewBox="0 0 12 12" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
              <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </span>
        )}
      </button>

      {open && (
        <div
          id={listboxId}
          role="listbox"
          className={cx(
            'qara-dropdown-menu',
            align === 'right' ? 'right-0' : 'left-0',
            menuClassName,
          )}
        >
          {options.map(option => {
            const enabledIndex = enabledOptions.findIndex(item => item.value === option.value);
            const isSelected = option.value === value;
            const isActive = enabledIndex >= 0 && enabledIndex === activeIndex;

            return (
              <button
                key={String(option.value)}
                ref={node => {
                  if (enabledIndex >= 0) optionRefs.current[enabledIndex] = node;
                }}
                type="button"
                role="option"
                aria-selected={isSelected}
                disabled={option.disabled}
                tabIndex={isActive ? 0 : -1}
                onClick={() => !option.disabled && commit(option.value)}
                onMouseEnter={() => enabledIndex >= 0 && setActiveIndex(enabledIndex)}
                className={cx(
                  'qara-dropdown-option',
                  isSelected && 'qara-dropdown-option-selected',
                  isActive && 'qara-dropdown-option-active',
                  option.disabled && 'cursor-not-allowed opacity-50',
                  optionClassName,
                )}
              >
                <span className="truncate">{option.label}</span>
                {isSelected && (
                  <svg viewBox="0 0 16 16" fill="none" className="h-4 w-4 shrink-0 text-info" aria-hidden="true">
                    <path d="M3.5 8.5l3 3 6-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
