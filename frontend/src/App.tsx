import { useState, useEffect, lazy, Suspense, createContext, useContext, type FormEvent, type MouseEvent, type ReactNode } from 'react';
import { ProjectProvider, useProject } from './hooks/useProject';
import { Dropdown } from './components/Dropdown';
import { Tooltip } from './components/Tooltip';
import {
  Activity, AlertTriangle, BarChart3, ShieldAlert, GitCompare,
  MessageSquare, Moon, Sun, ChevronLeft, ChevronRight, FileDown, LogOut, Settings as SettingsIcon, type LucideIcon,
} from 'lucide-react';

const CompareEngine  = lazy(() => import('./compare-engine').then(m => ({ default: m.CompareEngine })));
const IncidentsPanel = lazy(() => import('./panels/IncidentsPanel').then(m => ({ default: m.IncidentsPanel })));
const RiskPanel      = lazy(() => import('./panels/RiskPanel').then(m => ({ default: m.RiskPanel })));
const AnalysisPanel  = lazy(() => import('./panels/AnalysisPanel').then(m => ({ default: m.AnalysisPanel })));
const RunsPanel      = lazy(() => import('./panels/RunsPanel').then(m => ({ default: m.RunsPanel })));
const ChatPanel      = lazy(() => import('./panels/ChatPanel').then(m => ({ default: m.ChatPanel })));
const SettingsPanel  = lazy(() => import('./panels/SettingsPanel').then(m => ({ default: m.SettingsPanel })));

const AUTH_TOKEN_KEY = 'qalens-auth-token';

function installAuthFetchInterceptor() {
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url;
    const sameOriginApi = url.startsWith('/api/') || url.startsWith(window.location.origin + '/api/');
    if (!sameOriginApi || url.includes('/api/auth/status')) {
      return originalFetch(input, init);
    }

    const token = sessionStorage.getItem(AUTH_TOKEN_KEY);
    if (!token) return originalFetch(input, init);

    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    if (!headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    return originalFetch(input, { ...init, headers });
  };
}

installAuthFetchInterceptor();

// ─────────────────────────────────────────────────────────────
// Auth context
// ─────────────────────────────────────────────────────────────

interface AuthContextValue {
  mode: 'none' | 'token' | 'github' | null;
  isAdmin: boolean;
  logout: () => void;
}
const AuthContext = createContext<AuthContextValue>({ mode: null, isAdmin: true, logout: () => {} });
function useAuthContext() { return useContext(AuthContext); }

interface GitHubUser { login: string; name: string | null; avatar_url: string | null; }

function useGitHubUser(): GitHubUser | null {
  const { mode } = useAuthContext();
  const [user, setUser] = useState<GitHubUser | null>(null);
  useEffect(() => {
    if (mode !== 'github') return;
    fetch('/api/auth/me')
      .then(r => r.ok ? r.json() : null)
      .then((data: { user?: GitHubUser } | null) => { if (data?.user) setUser(data.user); })
      .catch(() => {});
  }, [mode]);
  return user;
}

// ─────────────────────────────────────────────────────────────
// Tab definitions
// ─────────────────────────────────────────────────────────────

type TabId = 'compare' | 'incidents' | 'risk' | 'analysis' | 'runs' | 'chat' | 'settings';

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
  { id: 'settings',  label: 'Settings',  icon: SettingsIcon,  ready: true },
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
      return localStorage.getItem('qalens-theme') === 'dark';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try {
      localStorage.setItem('qalens-theme', dark ? 'dark' : 'light');
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

function reportExportHref(currentProject: string) {
  const params = new URLSearchParams({ format: 'html' });
  if (currentProject) params.set('project', currentProject);
  return `/api/report/export?${params.toString()}`;
}

async function downloadReport(currentProject: string) {
  const response = await fetch(reportExportHref(currentProject));
  if (!response.ok) throw new Error(`API ${response.status}`);
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = 'qalens-report.html';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
}

function GitHubUserFooter({ collapsed }: { collapsed: boolean }) {
  const { mode, logout } = useAuthContext();
  const user = useGitHubUser();
  if (mode !== 'github' || !user) return null;

  const separator = <div className="border-t border-slate-200 dark:border-slate-800 my-1" />;

  if (collapsed) {
    return (
      <>
        {separator}
        <Tooltip content={`@${user.login} · Sign out`} placement="right">
          <button
            onClick={logout}
            aria-label={`Sign out (@${user.login})`}
            className="flex w-full items-center justify-center rounded-xl py-2.5
                       text-slate-500 hover:bg-slate-100 hover:text-slate-950
                       dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white
                       transition-colors duration-150"
          >
            {user.avatar_url
              ? <img src={user.avatar_url} alt={user.login} className="h-6 w-6 rounded-full"
              onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }} />
              : <LogOut aria-hidden="true" className="h-[18px] w-[18px]" strokeWidth={2} />}
          </button>
        </Tooltip>
      </>
    );
  }

  return (
    <>
      {separator}
      <button
        onClick={logout}
        className="group flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium
                   text-slate-600 hover:bg-slate-100 hover:text-slate-950
                   dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white
                   transition-colors duration-150"
        aria-label="Sign out"
      >
        <LogOut
          aria-hidden="true"
          className="h-[18px] w-[18px] shrink-0 text-slate-500 group-hover:text-slate-900
                     dark:text-slate-400 dark:group-hover:text-white"
          strokeWidth={2}
        />
        <span className="flex-1">Sign out</span>
        {user.avatar_url && (
          <img src={user.avatar_url} alt={user.login} className="h-5 w-5 rounded-full shrink-0 opacity-80"
               onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }} />
        )}
      </button>
      <p className="px-3 pb-0.5 text-[11px] text-slate-400 dark:text-slate-500 truncate">
        @{user.login}
      </p>
    </>
  );
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
  const { isAdmin } = useAuthContext();
  const visibleTabs = TABS.filter(t => t.id !== 'settings' || isAdmin);

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
            <div className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-xl">
              <img src={`${import.meta.env.BASE_URL}qalens-icon.png`}      alt="QaLens" className="h-11 w-11 object-contain dark:hidden" />
              <img src={`${import.meta.env.BASE_URL}qalens-icon-dark.png`} alt="QaLens" className="hidden h-11 w-11 object-contain dark:block" />
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
          <div className="px-4 py-3.5 border-b border-slate-200 dark:border-slate-800">
            <div className="flex items-center justify-between gap-2">
              <a
                href={tabHref(activeTab, currentProject)}
                onClick={(event) => {
                  if (!shouldHandleClientSideNav(event)) return;
                  event.preventDefault();
                }}
                className="flex min-w-0 items-center gap-2.5"
                aria-label="QaLens"
              >
                <img
                  src={`${import.meta.env.BASE_URL}qalens-icon.png`}
                  alt=""
                  className="h-10 w-10 shrink-0 object-contain dark:hidden"
                  aria-hidden="true"
                />
                <img
                  src={`${import.meta.env.BASE_URL}qalens-icon-dark.png`}
                  alt=""
                  className="hidden h-10 w-10 shrink-0 object-contain dark:block"
                  aria-hidden="true"
                />
                <span className="truncate text-[22px] font-extrabold leading-none tracking-normal">
                  <span className="text-blue-600 dark:text-blue-400">QA</span>
                  <span className="text-slate-950 dark:text-white">Lens</span>
                </span>
              </a>
              <button
                onClick={onToggleCollapsed}
                className="hidden lg:inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg
                           text-slate-400 hover:text-slate-700 hover:bg-slate-100
                           dark:text-slate-500 dark:hover:text-slate-200 dark:hover:bg-slate-800
                           transition-colors duration-150"
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
          {visibleTabs.map(tab => {
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

        {/* ── Footer: report export + theme toggle ── */}
        <div className="px-2 pb-3 pt-2 border-t border-slate-200 dark:border-slate-800 space-y-1">
          {collapsed ? (
            <Tooltip content="Export report" placement="right">
              <button
                type="button"
                onClick={() => void downloadReport(currentProject)}
                className="group flex w-full items-center justify-center rounded-xl px-0 py-2.5
                           text-slate-500 hover:bg-slate-100 hover:text-slate-950
                           dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white
                           transition-colors duration-150"
                aria-label="Export QaLens report"
              >
                <FileDown aria-hidden="true" className="h-[18px] w-[18px] shrink-0" strokeWidth={2} />
              </button>
            </Tooltip>
          ) : (
            <button
              type="button"
              onClick={() => void downloadReport(currentProject)}
              className="group flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium
                         text-slate-600 hover:bg-slate-100 hover:text-slate-950
                         dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white
                         transition-colors duration-150"
              aria-label="Export QaLens report"
            >
              <FileDown aria-hidden="true" className="h-[18px] w-[18px] shrink-0 text-slate-500 group-hover:text-slate-900 dark:text-slate-400 dark:group-hover:text-white" strokeWidth={2} />
              <span>Export report</span>
            </button>
          )}
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
          <GitHubUserFooter collapsed={collapsed} />
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
      return localStorage.getItem('qalens-sidebar-collapsed') === 'true';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('qalens-sidebar-collapsed', sidebarCollapsed ? 'true' : 'false');
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
            {activeTab === 'settings'  && <SettingsPanel />}
          </Suspense>
        </main>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Root
// ─────────────────────────────────────────────────────────────

type AuthState =
  | { loading: true; required: false; authenticated: false; error: string | null }
  | { loading: false; required: false; authenticated: true; error: string | null }
  | { loading: false; required: true; authenticated: boolean; error: string | null };

function AuthGate({ children }: { children: ReactNode }) {
  const [token, setToken] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [authMode, setAuthMode] = useState<'none' | 'token' | 'github' | null>(null);
  const [isAdmin, setIsAdmin] = useState(true);
  const [state, setState] = useState<AuthState>({
    loading: true,
    required: false,
    authenticated: false,
    error: null,
  });

  function logout() {
    void fetch('/auth/logout', { method: 'POST' }).finally(() => {
      window.location.href = '/login';
    });
  }

  async function checkStatus(candidateToken?: string) {
    const headers = new Headers();
    if (candidateToken) headers.set('Authorization', `Bearer ${candidateToken}`);
    const response = await fetch('/api/auth/status', { headers });
    if (!response.ok) throw new Error(`API ${response.status}`);
    return response.json() as Promise<{
      mode?: 'none' | 'token' | 'github';
      required: boolean;
      authenticated: boolean;
      is_admin: boolean;
    }>;
  }

  useEffect(() => {
    let cancelled = false;
    const stored = sessionStorage.getItem(AUTH_TOKEN_KEY) ?? '';
    void checkStatus(stored || undefined)
      .then(status => {
        if (cancelled) return;
        setAuthMode(status.mode ?? 'none');
        setIsAdmin(status.is_admin ?? true);
        if (!status.required) {
          setState({ loading: false, required: false, authenticated: true, error: null });
          return;
        }
        if (status.mode === 'github') {
          if (status.authenticated) {
            setState({ loading: false, required: true, authenticated: true, error: null });
          } else {
            window.location.href = '/login';
          }
          return;
        }
        if (status.authenticated && stored) {
          setState({ loading: false, required: true, authenticated: true, error: null });
          return;
        }
        sessionStorage.removeItem(AUTH_TOKEN_KEY);
        setState({ loading: false, required: true, authenticated: false, error: null });
      })
      .catch(err => {
        if (!cancelled) {
          setState({
            loading: false,
            required: true,
            authenticated: false,
            error: err instanceof Error ? err.message : 'Could not verify authentication.',
          });
        }
      });
    return () => { cancelled = true; };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) return;
    setSubmitting(true);
    setState(prev => ({ ...prev, error: null }));
    try {
      const status = await checkStatus(trimmed);
      if (status.mode === 'github' && !status.authenticated) {
        window.location.href = '/login';
        return;
      }
      if (!status.required || status.authenticated) {
        sessionStorage.setItem(AUTH_TOKEN_KEY, trimmed);
        setState({ loading: false, required: status.required, authenticated: true, error: null });
      } else {
        sessionStorage.removeItem(AUTH_TOKEN_KEY);
        setState({ loading: false, required: true, authenticated: false, error: 'Invalid token.' });
      }
    } catch (err) {
      setState({
        loading: false,
        required: true,
        authenticated: false,
        error: err instanceof Error ? err.message : 'Could not verify token.',
      });
    } finally {
      setSubmitting(false);
    }
  }

  if (state.loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-page text-primary">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-slate-200 border-t-indigo-500 dark:border-slate-800 dark:border-t-indigo-400" />
      </div>
    );
  }

  if (state.required && !state.authenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-page px-4 text-primary">
        <form
          onSubmit={handleSubmit}
          className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950"
        >
          <div className="mb-5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">QaLens admin access</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">Enter admin token</h1>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              This server requires a bearer token before QaLens can read data or update settings.
            </p>
          </div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-200" htmlFor="qalens-auth-token">
            Token
          </label>
          <input
            id="qalens-auth-token"
            type="password"
            value={token}
            onChange={event => setToken(event.target.value)}
            autoFocus
            autoComplete="off"
            className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-950 outline-none transition focus:border-indigo-400 focus:ring-4 focus:ring-indigo-500/10 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-50"
          />
          {state.error && (
            <p className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
              {state.error}
            </p>
          )}
          <button
            type="submit"
            disabled={!token.trim() || submitting}
            className="mt-5 w-full rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Checking...' : 'Unlock QaLens'}
          </button>
        </form>
      </div>
    );
  }

  return (
    <AuthContext.Provider value={{ mode: authMode, isAdmin, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export default function App() {
  return (
    <AuthGate>
      <ProjectProvider>
        <Shell />
      </ProjectProvider>
    </AuthGate>
  );
}
