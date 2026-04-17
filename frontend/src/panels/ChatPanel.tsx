import {
  useState,
  useEffect,
  useRef,
  useCallback,
} from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { useProject } from '../hooks/useProject';

// ─────────────────────────────────────────────────────────────
// Markdown helper
// ─────────────────────────────────────────────────────────────

marked.setOptions({ breaks: true, gfm: true });

function renderMarkdown(raw: string): string {
  const html = marked.parse(raw) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ['target', 'rel'] });
}

// ─────────────────────────────────────────────────────────────
// API types
// ─────────────────────────────────────────────────────────────

interface ApiHomepageCard {
  id:        string;
  icon:      string;
  title:     string;
  metric:    string | null;
  question:  string;
  available: boolean;
}

interface ApiSource {
  type:     string;
  icon:     string;
  label:    string;
  meta:     string;
  run_id?:  string;
  name?:    string; // test canonical_name
}

interface ApiAskResponse {
  answer:       string;
  context_mode: string;
  sources:      ApiSource[];
  intent:       string;
  follow_ups:   string[];
}

interface ApiLlmInfo {
  provider: string;
  model: string;
}

interface ApiEvidenceRun {
  type:          'run';
  run_id:        string;
  title:         string;
  project:       string | null;
  started_at:    string | null;
  total_tests:   number;
  passed_count:  number;
  failed_count:  number;
  skipped_count: number;
  top_failed:    { name: string; status: string; error_type: string | null; message: string | null }[];
}

interface ApiEvidenceTest {
  type:            'test';
  canonical_name:  string;
  title:           string;
  classification:  string;
  risk_tier:       string;
  risk_pct:        number;
  pass_rate:       number;
  flip_score:      number;
  run_count:       number;
  sparkline:       string;
  why_relevant:    string[];
  recent_runs:     { run_id: string; run_label: string; status: string; timestamp: string }[];
  most_frequent_error: { category: string; message: string } | null;
}

type ApiEvidence = ApiEvidenceRun | ApiEvidenceTest;

// ─────────────────────────────────────────────────────────────
// Message types
// ─────────────────────────────────────────────────────────────

interface ConvMessage {
  id:         string;
  role:       'user' | 'assistant';
  content:    string;
  sources?:   ApiSource[];
  followUps?: string[];
  loading?:   boolean;
}

// ─────────────────────────────────────────────────────────────
// Evidence Drawer
// ─────────────────────────────────────────────────────────────

function EvidenceDrawer({
  source,
  allSources,
  currentIndex,
  onNavigate,
  onClose,
  project,
}: {
  source:       ApiSource;
  allSources:   ApiSource[];
  currentIndex: number;
  onNavigate:   (idx: number) => void;
  onClose:      () => void;
  project:      string;
}) {
  const [evidence, setEvidence] = useState<ApiEvidence | null>(null);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setEvidence(null);

    let url = '';
    if (source.run_id) {
      url = `/api/evidence/run/${encodeURIComponent(source.run_id)}`;
    } else if (source.type === 'test' && source.name) {
      url = `/api/evidence/test/${encodeURIComponent(source.name)}`;
    } else if (source.type === 'test' && source.label) {
      // Fallback: use label as canonical name
      url = `/api/evidence/test/${encodeURIComponent(source.label.toLowerCase().replace(/[()]/g, ''))}`;
    }

    if (!url) { setLoading(false); return; }

    fetch(url)
      .then(r => r.ok ? r.json() as Promise<ApiEvidence> : Promise.reject(`API ${r.status}`))
      .then(d => { if (!cancelled) setEvidence(d); })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [source]);

  function openInNewTab() {
    const params = new URLSearchParams({ tab: source.run_id ? 'runs' : 'analysis' });
    if (project) params.set('project', project);
    if (source.run_id) params.set('run', source.run_id);
    window.open(`/?${params}`, '_blank', 'noopener');
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <aside
        className="fixed top-0 right-0 h-full w-full max-w-md z-50
                   bg-zinc-900 border-l border-zinc-800 flex flex-col shadow-2xl"
        aria-label="Evidence details"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
          <div className="flex items-center gap-2">
            <span className="text-lg">{source.icon}</span>
            <span className="text-sm font-semibold text-zinc-200">{source.label}</span>
          </div>
          <div className="flex items-center gap-2">
            {/* Prev/Next */}
            {allSources.length > 1 && (
              <div className="flex gap-1">
                <button
                  onClick={() => onNavigate(currentIndex - 1)}
                  disabled={currentIndex === 0}
                  className="p-1.5 rounded text-zinc-400 hover:text-zinc-100 disabled:opacity-30
                             disabled:cursor-not-allowed border border-zinc-700 hover:border-zinc-500"
                  aria-label="Previous source"
                >
                  <svg viewBox="0 0 14 14" fill="none" className="w-3.5 h-3.5">
                    <path d="M9 3l-4 4 4 4" stroke="currentColor" strokeWidth="1.5"
                          strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </button>
                <button
                  onClick={() => onNavigate(currentIndex + 1)}
                  disabled={currentIndex >= allSources.length - 1}
                  className="p-1.5 rounded text-zinc-400 hover:text-zinc-100 disabled:opacity-30
                             disabled:cursor-not-allowed border border-zinc-700 hover:border-zinc-500"
                  aria-label="Next source"
                >
                  <svg viewBox="0 0 14 14" fill="none" className="w-3.5 h-3.5">
                    <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5"
                          strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </button>
                <span className="ml-1 text-xs text-zinc-500 self-center">
                  {currentIndex + 1}/{allSources.length}
                </span>
              </div>
            )}
            <button
              onClick={openInNewTab}
              className="p-1.5 rounded text-zinc-400 hover:text-zinc-100
                         border border-zinc-700 hover:border-zinc-500"
              title="Open in panel"
            >
              <svg viewBox="0 0 14 14" fill="none" className="w-3.5 h-3.5">
                <path d="M6 2H3a1 1 0 00-1 1v8a1 1 0 001 1h8a1 1 0 001-1v-3M8 2h4m0 0v4m0-4L7 7"
                      stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded text-zinc-400 hover:text-zinc-100
                         border border-zinc-700 hover:border-zinc-500"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {loading && (
            <div className="space-y-3 animate-pulse">
              {[1, 2, 3].map(i => <div key={i} className="h-10 rounded-lg bg-zinc-800" />)}
            </div>
          )}
          {error && (
            <p className="text-sm text-red-400">Failed to load evidence: {error}</p>
          )}
          {evidence?.type === 'run' && <RunEvidenceView data={evidence} />}
          {evidence?.type === 'test' && <TestEvidenceView data={evidence} />}
        </div>
      </aside>
    </>
  );
}

function RunEvidenceView({ data }: { data: ApiEvidenceRun }) {
  const passRate = data.total_tests > 0 ? Math.round(data.passed_count / data.total_tests * 100) : null;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Total',  value: data.total_tests,   cls: 'text-zinc-100' },
          { label: 'Passed', value: data.passed_count,  cls: 'text-green-400' },
          { label: 'Failed', value: data.failed_count,  cls: 'text-red-400' },
          ...(passRate != null ? [{ label: 'Pass Rate', value: `${passRate}%`, cls: passRate >= 80 ? 'text-green-400' : 'text-red-400' }] : []),
        ].map(c => (
          <div key={c.label} className="px-3 py-2 rounded-lg bg-zinc-800 border border-zinc-700">
            <span className="text-xs text-zinc-500">{c.label}</span>
            <div className={`text-xl font-bold tabular-nums ${c.cls}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {data.top_failed.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Top Failures
          </p>
          <div className="space-y-2">
            {data.top_failed.slice(0, 5).map((t, i) => (
              <div key={i} className="px-3 py-2 rounded-lg bg-zinc-800 border border-zinc-700">
                <p className="text-sm text-zinc-200 truncate">{t.name}</p>
                {t.error_type && (
                  <p className="text-xs text-red-400 mt-0.5">{t.error_type}</p>
                )}
                {t.message && (
                  <p className="text-xs text-zinc-500 mt-0.5 truncate">{t.message}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TestEvidenceView({ data }: { data: ApiEvidenceTest }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Classification', value: data.classification,        cls: 'text-zinc-200 text-sm' },
          { label: 'Risk Tier',      value: data.risk_tier.toUpperCase(), cls: 'text-amber-400' },
          { label: 'Pass Rate',      value: `${Math.round(data.pass_rate * 100)}%`, cls: data.pass_rate >= 0.8 ? 'text-green-400' : 'text-red-400' },
          { label: 'Runs',           value: String(data.run_count),     cls: 'text-zinc-200' },
        ].map(c => (
          <div key={c.label} className="px-3 py-2 rounded-lg bg-zinc-800 border border-zinc-700">
            <span className="text-xs text-zinc-500">{c.label}</span>
            <div className={`font-bold ${c.cls}`}>{c.value}</div>
          </div>
        ))}
      </div>

      {data.why_relevant.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Why It's Relevant
          </p>
          <ul className="space-y-1.5">
            {data.why_relevant.map((w, i) => (
              <li key={i} className="flex gap-2 text-sm text-zinc-400">
                <span className="text-zinc-600 shrink-0 mt-0.5">•</span>
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.recent_runs.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-2">
            Recent Runs
          </p>
          <div className="space-y-1.5">
            {data.recent_runs.slice(0, 6).map((r, i) => (
              <div key={i}
                   className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-zinc-800">
                <span className="text-xs text-zinc-400">{r.run_label}</span>
                <span className={`text-xs font-semibold
                                  ${r.status === 'passed' ? 'text-green-400' : r.status === 'skipped' ? 'text-zinc-500' : 'text-red-400'}`}>
                  {r.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Message bubble
// ─────────────────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] px-4 py-3 rounded-2xl rounded-tr-sm
                      bg-indigo-600 text-white text-sm leading-relaxed">
        {content}
      </div>
    </div>
  );
}

function AssistantBubble({
  msg,
  onSourceClick,
  onFollowUp,
}: {
  msg:           ConvMessage;
  onSourceClick: (source: ApiSource, allSources: ApiSource[], idx: number) => void;
  onFollowUp:    (q: string) => void;
}) {
  const sources = msg.sources ?? [];

  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-3">
        {/* Content */}
        <div className="px-4 py-3 rounded-2xl rounded-tl-sm
                        bg-white border border-zinc-200 dark:bg-zinc-800 dark:border-zinc-700">
          {msg.loading ? (
            <div className="flex items-center gap-2 text-sm text-zinc-400 dark:text-zinc-400">
              <span className="animate-pulse">●</span>
              <span className="animate-pulse animation-delay-200">●</span>
              <span className="animate-pulse animation-delay-400">●</span>
            </div>
          ) : (
            <div
              className="prose prose-base max-w-none text-zinc-900 dark:prose-invert dark:text-zinc-100
                         prose-p:my-1 prose-ul:my-1 prose-li:my-0.5
                         prose-headings:text-zinc-900 dark:prose-headings:text-zinc-200
                         prose-strong:text-zinc-900 dark:prose-strong:text-zinc-100
                         prose-code:text-indigo-600 dark:prose-code:text-indigo-300
                         prose-code:bg-zinc-100 dark:prose-code:bg-zinc-900 prose-code:px-1 prose-code:py-0.5
                         prose-code:rounded prose-code:text-[0.85em] prose-li:text-[1rem] prose-p:text-[1rem]"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
            />
          )}
        </div>

        {/* Source cards */}
        {!msg.loading && sources.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {sources.slice(0, 3).map((s, i) => (
              <button
                key={i}
                onClick={() => onSourceClick(s, sources, i)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs
                           bg-white border border-zinc-200 text-zinc-600
                           hover:border-indigo-400/50 hover:text-zinc-900
                           dark:bg-zinc-900 dark:border-zinc-700 dark:text-zinc-400
                           dark:hover:border-indigo-500/50 dark:hover:text-zinc-200 transition-colors"
              >
                <span>{s.icon}</span>
                <span className="font-medium">{s.label}</span>
                {s.meta && <span className="text-zinc-400 dark:text-zinc-600">· {s.meta}</span>}
              </button>
            ))}
            {sources.length > 3 && (
              <button
                onClick={() => onSourceClick(sources[3], sources, 3)}
                className="px-2.5 py-1.5 rounded-lg text-xs bg-white border
                           border-zinc-200 text-zinc-500 hover:text-zinc-800
                           dark:bg-zinc-900 dark:border-zinc-700 dark:text-zinc-500
                           dark:hover:text-zinc-300 transition-colors"
              >
                +{sources.length - 3} more
              </button>
            )}
          </div>
        )}

        {/* Follow-up chips */}
        {!msg.loading && msg.followUps && msg.followUps.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {msg.followUps.map((q, i) => (
              <button
                key={i}
                onClick={() => onFollowUp(q)}
                className="px-2.5 py-1 rounded-full text-xs border border-zinc-200
                           text-zinc-600 hover:text-zinc-900 hover:border-zinc-300
                           bg-white dark:border-zinc-700 dark:text-zinc-400
                           dark:hover:text-zinc-100 dark:hover:border-zinc-500
                           dark:bg-zinc-900 transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// ChatPanel
// ─────────────────────────────────────────────────────────────

export function ChatPanel() {
  const { currentProject } = useProject();

  const [messages,     setMessages]     = useState<ConvMessage[]>([]);
  const [input,        setInput]        = useState('');
  const [sending,      setSending]      = useState(false);
  const [cards,        setCards]        = useState<ApiHomepageCard[]>([]);
  const [drawerSource, setDrawerSource] = useState<{ source: ApiSource; all: ApiSource[]; idx: number } | null>(null);
  const [llmInfo,      setLlmInfo]      = useState<ApiLlmInfo | null>(null);

  const textareaRef  = useRef<HTMLTextAreaElement>(null);
  const bottomRef    = useRef<HTMLDivElement>(null);
  const idCounter    = useRef(0);
  const uid          = () => String(++idCounter.current);

  // Fetch homepage cards on mount / project change
  useEffect(() => {
    const params = new URLSearchParams();
    if (currentProject) params.set('project', currentProject);
    fetch(`/api/homepage-cards?${params}`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => setCards((d.cards ?? []) as ApiHomepageCard[]))
      .catch(() => {}); // silently ignore
  }, [currentProject]);

  useEffect(() => {
    fetch('/api/llm/info')
      .then(r => r.ok ? r.json() as Promise<ApiLlmInfo> : Promise.reject())
      .then(info => setLlmInfo(info))
      .catch(() => {});
  }, []);

  // Auto-scroll to bottom on new message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-grow textarea
  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }

  function buildHistory(): { role: string; content: string }[] {
    return messages
      .filter(m => !m.loading)
      .slice(-12) // last 6 exchanges (12 messages)
      .map(m => ({ role: m.role, content: m.content }));
  }

  const send = useCallback(async (question: string) => {
    const q = question.trim();
    if (!q || sending) return;

    // Add user message
    const userMsg: ConvMessage = { id: uid(), role: 'user', content: q };
    const loadingMsg: ConvMessage = { id: uid(), role: 'assistant', content: '', loading: true };
    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setInput('');
    setSending(true);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }

    const history = buildHistory();

    try {
      const res = await fetch('/api/ask', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ question: q, project: currentProject || null, history }),
      });

      if (!res.ok) throw new Error(`API ${res.status}`);
      const data: ApiAskResponse = await res.json();

      const assistantMsg: ConvMessage = {
        id:        loadingMsg.id,
        role:      'assistant',
        content:   data.answer,
        sources:   data.sources,
        followUps: data.follow_ups,
      };

      setMessages(prev => prev.map(m => m.id === loadingMsg.id ? assistantMsg : m));
    } catch (e) {
      const errorMsg: ConvMessage = {
        id:      loadingMsg.id,
        role:    'assistant',
        content: `Sorry, something went wrong: ${e instanceof Error ? e.message : String(e)}`,
      };
      setMessages(prev => prev.map(m => m.id === loadingMsg.id ? errorMsg : m));
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  }, [sending, currentProject, messages]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      send(input);
    }
  }

  function handleNewConversation() {
    setMessages([]);
    setInput('');
    setTimeout(() => textareaRef.current?.focus(), 50);
  }

  const showWelcome = messages.length === 0;

  return (
    <div className="flex flex-col h-full min-h-0" style={{ height: 'calc(100vh - 8rem)' }}>

      {/* Evidence drawer */}
      {drawerSource && (
        <EvidenceDrawer
          source={drawerSource.source}
          allSources={drawerSource.all}
          currentIndex={drawerSource.idx}
          onNavigate={idx => setDrawerSource(prev => prev ? { ...prev, source: prev.all[idx], idx } : null)}
          onClose={() => setDrawerSource(null)}
          project={currentProject}
        />
      )}

      {/* Main content area */}
      <div className="flex-1 overflow-y-auto space-y-1 pb-4">

        {/* Welcome screen */}
        {showWelcome && (
          <div className="flex flex-col items-center pt-8 pb-4 gap-6">
            <div className="text-center">
              <h2 className="text-xl font-semibold text-zinc-100">How can I help?</h2>
              <p className="text-sm text-zinc-500 mt-1">
                Ask anything about your test suite
              </p>
            </div>

            {/* Dynamic insight cards */}
            {cards.length > 0 && (
              <div className="grid grid-cols-2 gap-3 w-full max-w-lg">
                {cards.map(card => (
                  <button
                    key={card.id}
                    onClick={() => send(card.question)}
                    disabled={!card.available}
                    className="flex flex-col gap-1.5 p-3 rounded-xl text-left
                               bg-zinc-900 border border-zinc-800
                               hover:border-indigo-500/50 hover:bg-zinc-800/80
                               disabled:opacity-40 disabled:cursor-not-allowed
                               transition-colors group"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{card.icon}</span>
                      <span className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
                        {card.title}
                      </span>
                    </div>
                    {card.metric && (
                      <span className="text-sm font-semibold text-zinc-200">
                        {card.metric}
                      </span>
                    )}
                    <span className="text-xs text-zinc-500 group-hover:text-zinc-400 transition-colors">
                      {card.question}
                    </span>
                  </button>
                ))}
              </div>
            )}

          </div>
        )}

        {/* Message list */}
        {!showWelcome && (
          <div className="space-y-4 pt-4">
            {messages.map(msg => (
              msg.role === 'user'
                ? <UserBubble key={msg.id} content={msg.content} />
                : (
                  <AssistantBubble
                    key={msg.id}
                    msg={msg}
                    onSourceClick={(s, all, i) => setDrawerSource({ source: s, all, idx: i })}
                    onFollowUp={q => send(q)}
                  />
                )
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="shrink-0 border-t border-zinc-800 pt-3">
        {/* New conversation + context label */}
        {!showWelcome && (
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-zinc-600">
              {messages.filter(m => m.role === 'user').length} message{messages.filter(m => m.role === 'user').length !== 1 ? 's' : ''}
            </span>
            <button
              onClick={handleNewConversation}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              New conversation
            </button>
          </div>
        )}

        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your tests… (Ctrl+Enter to send)"
            rows={1}
            disabled={sending}
            className="flex-1 resize-none px-4 py-3 text-sm bg-zinc-900 border border-zinc-700
                       rounded-xl text-zinc-200 placeholder-zinc-600 focus:outline-none
                       focus:ring-2 focus:ring-indigo-500 focus:border-transparent
                       disabled:opacity-50 overflow-hidden leading-relaxed"
            style={{ minHeight: '48px', maxHeight: '200px' }}
          />
          <button
            onClick={() => send(input)}
            disabled={!input.trim() || sending}
            className="shrink-0 px-4 py-3 rounded-xl bg-indigo-600 text-white text-sm
                       font-medium hover:bg-indigo-500 disabled:opacity-40
                       disabled:cursor-not-allowed transition-colors"
            aria-label="Send message"
          >
            {sending ? (
              <span className="animate-spin inline-block w-4 h-4 border-2 border-white/30
                               border-t-white rounded-full" />
            ) : (
              <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4">
                <path d="M13 8L3 3l2 5-2 5 10-5z" stroke="currentColor" strokeWidth="1.5"
                      strokeLinejoin="round"/>
              </svg>
            )}
          </button>
        </div>
        <div className="mt-1.5 grid grid-cols-[1fr_auto_1fr] items-center gap-3 text-xs text-zinc-500">
          <span />
          <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-white px-2.5 py-1 text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
            <span>Answers powered by</span>
            <span className="font-medium text-zinc-700 dark:text-zinc-200">
              {llmInfo?.model ?? 'Gemma'}
            </span>
          </span>
          <span className="justify-self-end">Ctrl+Enter to send</span>
        </div>
      </div>
    </div>
  );
}
