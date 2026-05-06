import { useState, useEffect, lazy, Suspense, type MouseEvent } from 'react';
import { ProjectProvider, useProject } from './hooks/useProject';
import { Dropdown } from './components/Dropdown';
import { Tooltip } from './components/Tooltip';
import {
  Activity, AlertTriangle, BarChart3, ShieldAlert, GitCompare,
  MessageSquare, Moon, Sun, ChevronLeft, ChevronRight, type LucideIcon,
} from 'lucide-react';

const CompareEngine  = lazy(() => import('./compare-engine').then(m => ({ default: m.CompareEngine })));
const IncidentsPanel = lazy(() => import('./panels/IncidentsPanel').then(m => ({ default: m.IncidentsPanel })));
const RiskPanel      = lazy(() => import('./panels/RiskPanel').then(m => ({ default: m.RiskPanel })));
const AnalysisPanel  = lazy(() => import('./panels/AnalysisPanel').then(m => ({ default: m.AnalysisPanel })));
const RunsPanel      = lazy(() => import('./panels/RunsPanel').then(m => ({ default: m.RunsPanel })));
const ChatPanel      = lazy(() => import('./panels/ChatPanel').then(m => ({ default: m.ChatPanel })));

// ─────────────────────────────────────────────────────────────
// Tab definitions
// ─────────────────────────────────────────────────────────────

type TabId = 'compare' | 'incidents' | 'risk' | 'analysis' | 'runs' | 'chat';

interface Tab {
  id:    TabId;
  label: string;
  icon:  LucideIcon;
  ready: boolean;
}

const TABS: Tab[] = [
  { id: 'runs',      label: 'Runs',      icon: Activity,      ready: true },
  { id: 'incidents', label: 'Incidents', icon: AlertTriangle, ready: true },
  { id: 'analysis',  label: 'Analysis',  icon: BarChart3,     ready: true },
  { id: 'risk',      label: 'Risk',      icon: ShieldAlert,   ready: true },
  { id: 'compare',   label: 'Compare',   icon: GitCompare,    ready: true },
  { id: 'chat',      label: 'Chat',      icon: MessageSquare, ready: true },
];

// ─────────────────────────────────────────────────────────────
// Project selector
// ─────────────────────────────────────────────────────────────

function ProjectSelector() {
  const { currentProject, projects, setProject, loading } = useProject();

  if (loading) {
    return (
      <div className="h-11 rounded-[0.95rem] bg-surface-subtle animate-pulse" />
    );
  }

  if (projects.length === 0) {
    return (
      <div className="px-1 py-1.5 text-xs text-muted">No projects found</div>
    );
  }

  return (
    <Dropdown
      value={currentProject}
      onChange={setProject}
      ariaLabel="Select project"
      fullWidth
      triggerClassName="px-3.5 text-sm"
      options={[
        { value: '', label: 'All projects' },
        ...projects.map(project => ({ value: project, label: project })),
      ]}
    />
  );
}

// ─────────────────────────────────────────────────────────────
// Theme toggle
// ─────────────────────────────────────────────────────────────

function useTheme() {
  const [dark, setDark] = useState<boolean>(() => {
    try {
      return localStorage.getItem('qara-theme') === 'dark';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try {
      localStorage.setItem('qara-theme', dark ? 'dark' : 'light');
    } catch {
      // ignore storage failures
    }
  }, [dark]);

  return { dark, toggle: () => setDark(d => !d) };
}

// ─────────────────────────────────────────────────────────────
// Sidebar
// ─────────────────────────────────────────────────────────────

interface SidebarProps {
  activeTab:   TabId;
  onTabChange: (id: TabId) => void;
  open:        boolean;
  onClose:     () => void;
  collapsed:   boolean;
  onToggleCollapsed: () => void;
}

function tabHref(tab: TabId, currentProject: string) {
  const url = new URL(window.location.href);
  url.searchParams.set('tab', tab);
  if (currentProject) url.searchParams.set('project', currentProject);
  else url.searchParams.delete('project');
  return `${url.pathname}${url.search}${url.hash}`;
}

function shouldHandleClientSideNav(e: MouseEvent<HTMLAnchorElement>) {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

function Sidebar({
  activeTab,
  onTabChange,
  open,
  onClose,
  collapsed,
  onToggleCollapsed,
}: SidebarProps) {
  const { dark, toggle } = useTheme();
  const { currentProject } = useProject();

  return (
    <>
      {/* Mobile overlay scrim */}
      {open && (
        <div
          className="fixed inset-0 bg-slate-950/30 backdrop-blur-[2px] z-20 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={[
          'fixed top-0 left-0 h-full z-30 flex flex-col',
          'bg-white dark:bg-slate-950',
          'border-r border-slate-200 dark:border-slate-800',
          'shadow-[1px_0_0_0_rgba(15,23,42,0.06)] lg:shadow-none',
          'transition-[transform,width] duration-200 ease-out',
          open ? 'translate-x-0' : '-translate-x-full',
          'lg:translate-x-0 lg:static lg:z-auto',
          collapsed ? 'w-[220px] lg:w-[72px]' : 'w-[220px]',
        ].join(' ')}
        aria-label="Main navigation"
      >

        {/* ── Logo / header ── */}
        {collapsed ? (
          /* Collapsed: icon only, centered */
          <div className="flex flex-col items-center gap-2 py-3 px-2 border-b border-slate-200 dark:border-slate-800">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <img src={`${import.meta.env.BASE_URL}qara-logo.svg`}      alt="QARA" className="h-6 w-6 object-contain dark:hidden" />
              <img src={`${import.meta.env.BASE_URL}qara-logo-dark.svg`} alt="QARA" className="h-6 w-6 object-contain hidden dark:block" />
            </div>
            <button
              onClick={onToggleCollapsed}
              className="hidden lg:inline-flex h-6 w-6 items-center justify-center rounded-lg
                         text-slate-400 hover:text-slate-700 hover:bg-slate-100
                         dark:text-slate-500 dark:hover:text-slate-200 dark:hover:bg-slate-800
                         transition-colors duration-150"
              aria-label="Expand sidebar"
            >
              <ChevronRight aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={2} />
            </button>
          </div>
        ) : (
          /* Expanded: compact logo icon + wordmark + collapse button */
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <img src={`${import.meta.env.BASE_URL}qara-logo.svg`}      alt="QARA" className="dark:hidden" style={{ width: 130, height: 'auto' }} />
                <img src={`${import.meta.env.BASE_URL}qara-logo-dark.svg`} alt="QARA" className="hidden dark:block" style={{ width: 130, height: 'auto' }} />
                <p className="text-[9px] font-semibold uppercase tracking-[0.2em] text-slate-400 dark:text-slate-500 mt-1.5 px-0.5">Test Intelligence</p>
              </div>
              <button
                onClick={onToggleCollapsed}
                className="hidden lg:inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg
                           text-slate-400 hover:text-slate-700 hover:bg-slate-100
                           dark:text-slate-500 dark:hover:text-slate-200 dark:hover:bg-slate-800
                           transition-colors duration-150 mt-0.5"
                aria-label="Collapse sidebar"
              >
                <ChevronLeft aria-hidden="true" className="h-4 w-4" strokeWidth={2} />
              </button>
            </div>
          </div>
        )}

        {/* ── Project selector ── */}
        {!collapsed && (
          <div className="px-3 pt-4 pb-2">
            <label className="block text-[10px] font-semibold uppercase tracking-[0.22em]
                              text-slate-400 dark:text-slate-500 mb-1.5 px-0.5">
              Project
            </label>
            <ProjectSelector />
          </div>
        )}

        {/* ── Navigation ── */}
        <nav className="flex-1 px-2 pt-2 pb-2 overflow-y-auto space-y-0.5" aria-label="Panels">
          {TABS.map(tab => {
            const isActive = activeTab === tab.id;
            const navItem = (
              <a
                key={tab.id}
                href={tabHref(tab.id, currentProject)}
                onClick={e => {
                  if (!shouldHandleClientSideNav(e)) return;
                  e.preventDefault();
                  onTabChange(tab.id);
                  onClose();
                }}
                className={[
                  'group flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium select-none',
                  'transition-colors duration-150',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/40',
                  collapsed ? 'lg:justify-center lg:px-0' : '',
                  isActive
                    ? 'bg-indigo-50 text-indigo-700 border border-indigo-100 dark:bg-indigo-500/15 dark:text-indigo-300 dark:border-indigo-400/20'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950 border border-transparent dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white',
                  !tab.ready && !isActive ? 'opacity-40' : '',
                ].join(' ')}
                aria-current={isActive ? 'page' : undefined}
              >
                <tab.icon
                  aria-hidden="true"
                  className={[
                    'h-[18px] w-[18px] shrink-0 transition-colors duration-150',
                    isActive
                      ? 'text-indigo-600 dark:text-indigo-400'
                      : 'text-slate-500 group-hover:text-slate-900 dark:text-slate-400 dark:group-hover:text-white',
                  ].join(' ')}
                  strokeWidth={2}
                />
                {!collapsed && <span className="truncate">{tab.label}</span>}
                {!collapsed && !tab.ready && (
                  <span className="ml-auto text-[10px] font-mono text-slate-400
                                   bg-slate-100 dark:bg-slate-800 dark:text-slate-500
                                   px-1.5 py-0.5 rounded-full border border-slate-200 dark:border-slate-700">
                    soon
                  </span>
                )}
              </a>
            );

            return collapsed ? (
              <Tooltip key={tab.id} content={tab.label} placement="right">
                {navItem}
              </Tooltip>
            ) : navItem;
          })}
        </nav>

        {/* ── Footer: theme toggle ── */}
        <div className="px-2 pb-3 pt-2 border-t border-slate-200 dark:border-slate-800">
          {collapsed ? (
            <Tooltip content={dark ? 'Light mode' : 'Dark mode'} placement="right">
              <button
                onClick={toggle}
                className="group flex w-full items-center justify-center rounded-xl px-0 py-2.5
                           text-slate-500 hover:bg-slate-100 hover:text-slate-950
                           dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white
                           transition-colors duration-150"
                aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {dark
                  ? <Sun  aria-hidden="true" className="h-[18px] w-[18px] shrink-0" strokeWidth={2} />
                  : <Moon aria-hidden="true" className="h-[18px] w-[18px] shrink-0" strokeWidth={2} />
                }
              </button>
            </Tooltip>
          ) : (
            <button
              onClick={toggle}
              className="group flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium
                         text-slate-600 hover:bg-slate-100 hover:text-slate-950
                         dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white
                         transition-colors duration-150"
              aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {dark
                ? <Sun  aria-hidden="true" className="h-[18px] w-[18px] shrink-0 text-slate-500 group-hover:text-slate-900 dark:text-slate-400 dark:group-hover:text-white" strokeWidth={2} />
                : <Moon aria-hidden="true" className="h-[18px] w-[18px] shrink-0 text-slate-500 group-hover:text-slate-900 dark:text-slate-400 dark:group-hover:text-white" strokeWidth={2} />
              }
              <span>{dark ? 'Light mode' : 'Dark mode'}</span>
            </button>
          )}
        </div>

      </aside>
    </>
  );
}

// ─────────────────────────────────────────────────────────────
// URL helpers
// ─────────────────────────────────────────────────────────────

function getTabFromUrl(): TabId {
  const param = new URLSearchParams(window.location.search).get('tab');
  return TABS.find(t => t.id === param)?.id ?? 'runs';
}

function setTabInUrl(tab: TabId) {
  const url = new URL(window.location.href);
  url.searchParams.set('tab', tab);
  window.history.replaceState(null, '', url.toString());
}

// ─────────────────────────────────────────────────────────────
// Shell
// ─────────────────────────────────────────────────────────────

function Shell() {
  const [activeTab, setActiveTab]     = useState<TabId>(getTabFromUrl);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('qara-sidebar-collapsed') === 'true';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('qara-sidebar-collapsed', sidebarCollapsed ? 'true' : 'false');
    } catch {
      // ignore storage failures
    }
  }, [sidebarCollapsed]);

  function handleTabChange(id: TabId) {
    setActiveTab(id);
    setTabInUrl(id);
  }

  const currentTab = TABS.find(t => t.id === activeTab)!;

  return (
    <div className="flex h-screen overflow-hidden bg-page text-primary">
      <Sidebar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed(c => !c)}
      />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile top bar */}
        <header className="lg:hidden flex items-center gap-3 px-4 py-3
                           border-b border-border-subtle
                           bg-surface">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-2 rounded-[0.8rem] text-muted hover:text-primary hover:bg-hover transition-colors"
            aria-label="Open navigation menu"
          >
            <svg viewBox="0 0 16 16" className="w-4 h-4 fill-current" aria-hidden="true">
              <path d="M1 3h14v1.5H1zm0 4.25h14v1.5H1zM1 11.5h14V13H1z"/>
            </svg>
          </button>
          <div className="flex items-center gap-2 min-w-0">
            <currentTab.icon aria-hidden="true" className="h-[18px] w-[18px] shrink-0 text-info" strokeWidth={2} />
            <span className="font-semibold text-primary text-sm truncate">
              {currentTab.label}
            </span>
          </div>
        </header>

        {/* Main content */}
        <main
          className={[
            'flex-1 min-h-0 p-5 lg:p-7',
            activeTab === 'chat'
              ? 'flex flex-col overflow-hidden'
              : 'overflow-auto',
          ].join(' ')}
        >
          <Suspense fallback={
            <div className="space-y-3 animate-pulse">
              {[1, 2, 3].map(i => <div key={i} className="h-16 rounded-2xl bg-surface-subtle" />)}
            </div>
          }>
            {activeTab === 'compare'   && <CompareEngine />}
            {activeTab === 'incidents' && <IncidentsPanel />}
            {activeTab === 'risk'      && <RiskPanel />}
            {activeTab === 'analysis'  && <AnalysisPanel />}
            {activeTab === 'runs'      && <RunsPanel />}
            {activeTab === 'chat'      && <ChatPanel />}
          </Suspense>
        </main>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Root
// ─────────────────────────────────────────────────────────────

export default function App() {
  return (
    <ProjectProvider>
      <Shell />
    </ProjectProvider>
  );
}
