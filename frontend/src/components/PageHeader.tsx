import type { ReactNode } from 'react';

type HeaderTier = 'full' | 'compact' | 'minimal';

interface PageHeaderProps {
  tier?: HeaderTier;
  title: ReactNode;
  description?: ReactNode;
  kicker?: ReactNode;
  icon?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  className?: string;
  titleAs?: 'h1' | 'h2' | 'h3';
}

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function PageHeader({
  tier = 'full',
  title,
  description,
  kicker,
  icon,
  meta,
  actions,
  className,
  titleAs = 'h1',
}: PageHeaderProps) {
  const TitleTag = titleAs;
  const hasBody = Boolean(kicker || description || meta);

  return (
    <div
      className={cx(
        'qara-page-header',
        tier === 'compact' && 'qara-page-header-compact',
        tier === 'minimal' && 'qara-page-header-minimal',
        className,
      )}
    >
      <div className={cx('qara-page-heading', tier === 'minimal' && 'items-center')}>
        {icon && <div className="qara-page-icon">{icon}</div>}
        <div className="min-w-0">
          {kicker && tier !== 'minimal' && (
            <p className="qara-page-kicker">{kicker}</p>
          )}
          <div className={cx('flex flex-wrap items-baseline gap-x-2 gap-y-1', !hasBody && 'min-h-[2rem]')}>
            <TitleTag className={cx('qara-page-title', tier === 'minimal' && 'qara-page-title-minimal')}>
              {title}
            </TitleTag>
            {meta && tier !== 'full' && (
              <div className="qara-page-meta">
                {meta}
              </div>
            )}
          </div>
          {description && tier === 'full' && (
            <p className="qara-page-subtitle">{description}</p>
          )}
        </div>
      </div>

      {actions && (
        <div className="flex items-center gap-2">
          {actions}
        </div>
      )}
    </div>
  );
}
