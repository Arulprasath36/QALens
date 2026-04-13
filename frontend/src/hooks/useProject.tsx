import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';

// ─────────────────────────────────────────────────────────────
// Context types
// ─────────────────────────────────────────────────────────────

interface ProjectContextValue {
  currentProject: string;
  projects:       string[];
  setProject:     (p: string) => void;
  loading:        boolean;
}

// ─────────────────────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────────────────────

const ProjectContext = createContext<ProjectContextValue | null>(null);

// ─────────────────────────────────────────────────────────────
// Provider
// ─────────────────────────────────────────────────────────────

export function ProjectProvider({ children }: { children: ReactNode }) {
  // Initialise from URL (?project=…) so deep-linked tabs open with the right project
  const urlProject = new URLSearchParams(window.location.search).get('project') ?? '';

  const [currentProject, setCurrentProject] = useState<string>(urlProject);
  const [projects,       setProjects]        = useState<string[]>([]);
  const [loading,        setLoading]          = useState(true);

  // Fetch project list on mount
  useEffect(() => {
    fetch('/api/projects')
      .then(r => r.json())
      .then((list: string[]) => {
        setProjects(list);
        // Auto-select only project if none was specified in the URL
        if (!currentProject && list.length === 1) {
          setCurrentProject(list[0]);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setProject = useCallback((p: string) => {
    setCurrentProject(p);
    // Update URL so link-sharing works
    const url = new URL(window.location.href);
    if (p) url.searchParams.set('project', p);
    else   url.searchParams.delete('project');
    window.history.replaceState(null, '', url.toString());
  }, []);

  return (
    <ProjectContext.Provider value={{ currentProject, projects, setProject, loading }}>
      {children}
    </ProjectContext.Provider>
  );
}

// ─────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────

export function useProject(): ProjectContextValue {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error('useProject must be used inside <ProjectProvider>');
  return ctx;
}
