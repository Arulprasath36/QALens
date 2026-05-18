interface TrophyIconProps {
  className?: string;
  width?: number;
  height?: number;
}

export function TrophyIcon({
  className,
  width = 13,
  height = 13,
}: TrophyIconProps) {
  return (
    <svg
      width={width}
      height={height}
      viewBox="0 0 16 16"
      fill="none"
      className={className}
      aria-hidden="true"
    >
      <path d="M5 2h6v2.2a3 3 0 0 1-6 0V2Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/>
      <path d="M5 3H3.5A1.5 1.5 0 0 0 2 4.5v.1A2.4 2.4 0 0 0 4.4 7H5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M11 3h1.5A1.5 1.5 0 0 1 14 4.5v.1A2.4 2.4 0 0 1 11.6 7H11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M8 7v2.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
      <path d="M6.2 11.5h3.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
      <path d="M5.4 13h5.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
    </svg>
  );
}
