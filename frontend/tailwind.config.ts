import type { Config } from 'tailwindcss';
import animate from 'tailwindcss-animate';

export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      // ── Semantic color tokens ─────────────────────────────────
      // Reference the CSS custom properties defined in index.css.
      // New code can use `bg-page`, `bg-surface`, `text-primary`,
      // `text-muted`, `bg-selected`, and semantic status colors.
      colors: {
        page:    'var(--bg-page)',
        surface: {
          DEFAULT: 'var(--bg-surface)',
          subtle:  'var(--bg-subtle)',
          raised:  'var(--bg-elevated)',
          control: 'var(--bg-control)',
        },
        border: {
          subtle:  'var(--border-subtle)',
          DEFAULT: 'var(--border-default)',
          strong:  'var(--border-strong)',
        },
        // Backwards-compatible alias for older code paths.
        rim: {
          subtle:  'var(--border-subtle)',
          DEFAULT: 'var(--border-default)',
          strong:  'var(--border-strong)',
        },
        success: 'rgb(var(--success-rgb) / <alpha-value>)',
        warning: 'rgb(var(--warning-rgb) / <alpha-value>)',
        danger:  'rgb(var(--danger-rgb) / <alpha-value>)',
        info:    'rgb(var(--info-rgb) / <alpha-value>)',
        hover:   'var(--bg-hover)',
        selected:'var(--bg-selected)',
      },
      textColor: {
        primary:   'var(--text-primary)',
        secondary: 'var(--text-secondary)',
        muted:     'var(--text-muted)',
        faint:     'var(--text-faint)',
      },
      boxShadow: {
        card:     'var(--shadow-card)',
        elevated: 'var(--shadow-elevated)',
        overlay:  'var(--shadow-overlay)',
      },
      // ── Typography scale ──────────────────────────────────────
      // Semantic named sizes. Use as: text-display-lg, text-heading-md,
      // text-body-sm, text-label-md, text-micro, etc.
      fontSize: {
        // Display — hero numbers, page headings
        'display-lg': ['2rem',     { lineHeight: '1.15', letterSpacing: '-0.03em',  fontWeight: '700' }],
        'display-md': ['1.75rem',  { lineHeight: '1.2',  letterSpacing: '-0.028em', fontWeight: '700' }],
        'display-sm': ['1.5rem',   { lineHeight: '1.25', letterSpacing: '-0.024em', fontWeight: '600' }],
        // Headings — section titles, card headers
        'heading-lg': ['1.25rem',  { lineHeight: '1.3',  letterSpacing: '-0.018em', fontWeight: '600' }],
        'heading-md': ['1.125rem', { lineHeight: '1.35', letterSpacing: '-0.014em', fontWeight: '600' }],
        'heading-sm': ['1rem',     { lineHeight: '1.4',  letterSpacing: '-0.01em',  fontWeight: '600' }],
        // Body — primary UI text
        'body-lg': ['1rem',       { lineHeight: '1.6',  letterSpacing: '-0.005em', fontWeight: '400' }],
        'body-md': ['0.9375rem',  { lineHeight: '1.55', letterSpacing: '-0.003em', fontWeight: '400' }],
        'body-sm': ['0.875rem',   { lineHeight: '1.5',  letterSpacing: '0em',      fontWeight: '400' }],
        // Labels / UI metadata
        'label-lg': ['0.875rem',  { lineHeight: '1.4',  letterSpacing: '0em',      fontWeight: '500' }],
        'label-md': ['0.8125rem', { lineHeight: '1.4',  letterSpacing: '0.005em',  fontWeight: '500' }],
        'label-sm': ['0.75rem',   { lineHeight: '1.35', letterSpacing: '0.005em',  fontWeight: '500' }],
        // Micro / eyebrow — uppercase labels, table headers, stat card labels
        'micro':    ['0.6875rem', { lineHeight: '1.3',  letterSpacing: '0.08em',   fontWeight: '600' }],
        'micro-xs': ['0.625rem',  { lineHeight: '1.3',  letterSpacing: '0.1em',    fontWeight: '600' }],
      },
      // Semantic tracking values
      letterSpacing: {
        'display': '-0.03em',
        'heading': '-0.018em',
        'metric':  '-0.045em',
        'label':   '0.08em',
        'eyebrow': '0.12em',
      },
      // ── Typography refinements ────────────────────────────────
      fontFamily: {
        sans: [
          'Inter',
          'SF Pro Display',
          'SF Pro Text',
          'Avenir Next',
          'Segoe UI',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono', 'Fira Code', 'Cascadia Code',
          'SF Mono', 'Consolas', 'monospace',
        ],
      },
    },
  },
  plugins: [animate],
} satisfies Config;
