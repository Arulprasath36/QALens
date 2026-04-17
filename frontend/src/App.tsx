import { useState, useEffect } from 'react';
import { ProjectProvider, useProject } from './hooks/useProject';
import { CompareEngine } from './compare-engine';
import { Dropdown } from './components/Dropdown';
import { IncidentsPanel } from './panels/IncidentsPanel';
import { RiskPanel }      from './panels/RiskPanel';
import { AnalysisPanel }  from './panels/AnalysisPanel';
import { RunsPanel }      from './panels/RunsPanel';
import { ChatPanel }      from './panels/ChatPanel';

// ─────────────────────────────────────────────────────────────
// Tab definitions
// ─────────────────────────────────────────────────────────────

type TabId = 'compare' | 'incidents' | 'risk' | 'analysis' | 'runs' | 'chat';

interface Tab {
  id:    TabId;
  label: string;
  icon:  string;
  ready: boolean;
}

const TABS: Tab[] = [
  { id: 'runs',      label: 'Runs',      icon: '▶',   ready: true },
  { id: 'incidents', label: 'Incidents', icon: '🚨',  ready: true },
  { id: 'analysis',  label: 'Analysis',  icon: '📊',  ready: true },
  { id: 'risk',      label: 'Risk',      icon: '🎯',  ready: true },
  { id: 'compare',   label: 'Compare',   icon: '⚖',  ready: true },
  { id: 'chat',      label: 'Chat',      icon: '💬',  ready: true },
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
      placeholder="Select project..."
      fullWidth
      triggerClassName="px-3.5 text-sm"
      options={projects.map(project => ({ value: project, label: project }))}
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
}

function Sidebar({ activeTab, onTabChange, open, onClose }: SidebarProps) {
  const { dark, toggle } = useTheme();

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
          'fixed top-0 left-0 h-full w-[220px] z-30 flex flex-col',
          'bg-surface border-r border-border-subtle',
          'shadow-[0_16px_40px_rgba(15,23,42,0.04)] lg:shadow-none',
          'transition-transform duration-200 ease-out',
          open ? 'translate-x-0' : '-translate-x-full',
          'lg:translate-x-0 lg:static lg:z-auto',
        ].join(' ')}
        aria-label="Main navigation"
      >

        {/* ── Logo / wordmark ── */}
        <div className="flex items-center gap-3 px-4 py-[18px] border-b border-border-subtle">
          {/* App icon */}
          <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-[0.9rem] bg-selected border border-border-default shadow-sm">
            <svg viewBox="0 0 16 16" className="w-4 h-4 fill-current text-info" aria-hidden="true">
              <path d="M8 1a7 7 0 100 14A7 7 0 008 1zM3 8a5 5 0 1110 0 5 5 0 01-10 0z"/>
              <circle cx="11.5" cy="11.5" r="2.5" className="fill-current text-success" />
            </svg>
          </div>
          {/* Wordmark */}
          <div className="min-w-0">
            <div className="font-semibold text-primary text-sm tracking-tight leading-tight">
              QARA
            </div>
            <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-faint
                            leading-tight mt-px">
              Test Intelligence
            </div>
          </div>
        </div>

        {/* ── Project selector ── */}
        <div className="px-3 pt-4 pb-2">
          <label className="block text-[10px] font-semibold uppercase tracking-[0.16em]
                            text-faint mb-1.5 px-0.5">
            Project
          </label>
          <ProjectSelector />
        </div>

        {/* ── Navigation ── */}
        <nav className="flex-1 px-2 pt-1 pb-2 overflow-y-auto space-y-px" aria-label="Panels">
          {TABS.map(tab => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => { onTabChange(tab.id); onClose(); }}
                className={[
                  'qara-nav-item text-sm text-left select-none',
                  isActive
                    ? 'qara-nav-item-active font-medium'
                    : 'text-muted',
                  !tab.ready && !isActive ? 'opacity-50' : '',
                ].join(' ')}
                aria-current={isActive ? 'page' : undefined}
              >
                <span className="text-base leading-none" aria-hidden="true">
                  {tab.icon}
                </span>
                <span className="truncate">{tab.label}</span>
                {!tab.ready && (
                  <span className="ml-auto text-[10px] text-faint font-mono
                                   bg-surface-subtle px-1.5 py-0.5 rounded-full border border-border-subtle">
                    soon
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* ── Footer: theme toggle ── */}
        <div className="px-2 pb-3 pt-2 border-t border-border-subtle">
          <button
            onClick={toggle}
            className="qara-nav-item w-full text-sm"
            aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            <span className="text-base leading-none" aria-hidden="true">
              {dark ? '☀' : '🌙'}
            </span>
            <span>{dark ? 'Light mode' : 'Dark mode'}</span>
          </button>
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
            <span className="text-base leading-none" aria-hidden="true">{currentTab.icon}</span>
            <span className="font-semibold text-primary text-sm truncate">
              {currentTab.label}
            </span>
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-auto p-5 lg:p-7">
          {activeTab === 'compare'   && <CompareEngine />}
          {activeTab === 'incidents' && <IncidentsPanel />}
          {activeTab === 'risk'      && <RiskPanel />}
          {activeTab === 'analysis'  && <AnalysisPanel />}
          {activeTab === 'runs'      && <RunsPanel />}
          {activeTab === 'chat'      && <ChatPanel />}
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
