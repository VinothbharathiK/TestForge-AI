import React, { useMemo, useRef, useState, useEffect } from 'react';
import { AlertTriangle, Check, CheckCircle2, Clock, Copy, Cpu, Terminal } from 'lucide-react';
import { splitLogEntries, summarizeResult } from '../utils/resultPresentation';

function parseLog(entry) {
  const text = entry.message;
  const timeMatch = text.match(/^\[(\d{2}:\d{2}:\d{2})\]\s*/);
  const tagMatch = text.match(/\[(INFO|AGENT|MODEL|EXEC|SUCCESS|TEST|HEAL|DEFECT|WARN|ERROR)\]/i);
  const rawCategory = tagMatch?.[1]?.toUpperCase() || 'INFO';
  const category = ({ AGENT: 'INFO', SUCCESS: 'TEST', WARN: 'TEST', HEAL: 'REPAIR' })[rawCategory] || rawCategory;
  return {
    timestamp: timeMatch?.[1] || entry.timestamp,
    category,
    message: text.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, ''),
  };
}

const categoryColors = {
  INFO: 'text-slate-300',
  MODEL: 'text-purple-300',
  EXEC: 'text-sky-300',
  TEST: 'text-emerald-300',
  REPAIR: 'text-amber-300',
  DEFECT: 'text-rose-300',
  ERROR: 'text-rose-300',
};

export default function AgentLogs({
  logs = [],
  status,
  metrics,
  diagnosis,
  failureType,
}) {
  const [copied, setCopied] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef(null);
  const { visible, raw } = useMemo(() => splitLogEntries(logs), [logs]);
  const summary = useMemo(
    () => summarizeResult({ status, metrics, diagnosis, failureType, logs }),
    [status, metrics, diagnosis, failureType, logs],
  );

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [visible, status, autoScroll]);

  const handleCopyLogs = async () => {
    try {
      await navigator.clipboard.writeText(logs.map((entry) => (
        typeof entry === 'string' ? entry : entry?.message || JSON.stringify(entry)
      )).join('\n'));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy logs', error);
    }
  };

  const active = status !== 'idle';
  const summaryTone = status === 'success'
    ? 'border-emerald-800 bg-emerald-950/60 text-emerald-100'
    : status === 'defect_detected'
      ? 'border-rose-800 bg-rose-950/60 text-rose-100'
      : status === 'error' || failureType
        ? 'border-amber-800 bg-amber-950/50 text-amber-100'
        : 'border-slate-700 bg-slate-800/70 text-slate-100';

  return (
    <div className="flex flex-col h-full min-h-0 bg-slate-900 rounded-b-xl overflow-hidden text-slate-200">
      <div className="px-4 py-3 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between text-xs shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            <span className="w-3 h-3 rounded-full bg-rose-500/80 inline-block border border-rose-600/50" />
            <span className="w-3 h-3 rounded-full bg-amber-500/80 inline-block border border-amber-600/50" />
            <span className="w-3 h-3 rounded-full bg-emerald-500/80 inline-block border border-emerald-600/50" />
          </div>
          <span className="text-slate-400 font-mono text-[11px] flex items-center gap-1.5 border-l border-slate-800 pl-3">
            <Terminal className="w-3.5 h-3.5 text-purple-400" />
            testforge-agent: pytest-sandbox
          </span>
        </div>
        {logs.length > 0 && (
          <button
            type="button"
            onClick={handleCopyLogs}
            title="Copy all execution logs"
            aria-label="Copy all execution logs"
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-mono border border-slate-700"
          >
            {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
            {copied ? 'Copied' : 'Copy Logs'}
          </button>
        )}
      </div>

      {active && (
        <section aria-label="Execution summary" className={`mx-3 mt-3 rounded-lg border p-3 shrink-0 ${summaryTone}`}>
          <div className="flex items-start gap-2.5">
            {status === 'success'
              ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-400" />
              : status === 'defect_detected'
                ? <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-rose-300" />
                : <Clock className="w-4 h-4 mt-0.5 shrink-0 text-amber-300" />}
            <div className="min-w-0">
              <h3 className="font-semibold text-sm">{summary.title}</h3>
              {summary.exceptionHeadline && (
                <p className="mt-1 font-mono text-xs font-semibold text-amber-200 break-words">
                  {summary.exceptionHeadline}
                </p>
              )}
              <p className="text-xs mt-1 leading-relaxed whitespace-pre-wrap break-words">{summary.message}</p>
              {summary.details.length > 0 && (
                <p className="mt-2 text-[10px] leading-relaxed font-mono text-slate-300 break-words">
                  {summary.details.join('  ·  ')}
                </p>
              )}
              {diagnosis?.likely_cause && (
                <p className="mt-2 text-xs text-amber-100"><strong>Likely cause:</strong> {diagnosis.likely_cause}</p>
              )}
              {diagnosis?.suggestion && (
                <div className="mt-2">
                  <p className="text-xs font-semibold mb-1">Suggested fix (not applied):</p>
                  <pre className="max-h-28 overflow-auto rounded bg-slate-950/80 border border-slate-700 p-2 text-[11px] leading-5 font-mono whitespace-pre-wrap break-words">{diagnosis.suggestion}</pre>
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      <div
        ref={logContainerRef}
        role="log"
        aria-live="polite"
        className="flex-1 min-h-0 p-3 sm:p-4 overflow-y-auto space-y-2 font-mono scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900"
      >
        {status === 'idle' && logs.length === 0 && (
          <div className="h-full min-h-[240px] flex flex-col items-center justify-center text-center text-slate-500 py-8">
            <Cpu className="w-10 h-10 text-slate-700 mb-3" />
            <p className="font-mono text-sm text-slate-400 mb-1">TestForge Autonomous Agent: Standing By</p>
            <p className="text-xs text-slate-600 max-w-sm">Generate tests to see model activity, pytest results, and any repair steps.</p>
          </div>
        )}

        {visible.map((entry) => {
          const parsed = parseLog(entry);
          return (
            <div key={entry.id} className="grid grid-cols-[62px_48px_minmax(0,1fr)] gap-2 items-start text-[11px] sm:text-xs leading-5">
              <time className="text-slate-500 text-[10px] pt-0.5">{parsed.timestamp}</time>
              <span className={`font-bold text-[10px] pt-0.5 ${categoryColors[parsed.category] || 'text-slate-400'}`}>{parsed.category}</span>
              <span className={`min-w-0 whitespace-pre-wrap break-words ${categoryColors[parsed.category] || 'text-slate-300'}`}>{parsed.message}</span>
            </div>
          );
        })}

        {raw.length > 0 && (
          <details className="mt-3 rounded-lg border border-slate-700 bg-slate-950/60">
            <summary className="cursor-pointer px-3 py-2 text-xs font-sans font-medium text-slate-300 hover:text-white">
              View raw output / traceback ({raw.length} entries)
            </summary>
            <pre className="max-h-72 overflow-auto border-t border-slate-800 p-3 text-[11px] leading-5 text-slate-300 font-mono whitespace-pre-wrap break-words">{raw.map((entry) => entry.message).join('\n\n')}</pre>
          </details>
        )}

        {status === 'loading' && (
          <div className="pt-2 flex items-center gap-2 text-purple-300 text-xs animate-pulse">
            <span className="w-2 h-2 rounded-full bg-purple-400 inline-block" />
            Agent is generating tests and running isolated pytest verification…
          </div>
        )}
      </div>

      <div className="px-4 py-2.5 bg-slate-950 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400 font-mono shrink-0">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5 text-slate-500" />Sandbox: {metrics?.executionTimeMs != null ? `${metrics.executionTimeMs}ms` : '--'}</span>
          <span>Tests: {metrics?.testsCollected != null ? `${metrics.testsPassed || 0}/${metrics.testsCollected} passed` : '--'}</span>
          {metrics?.pytestExitCode != null && <span>Exit: {metrics.pytestExitCode}</span>}
        </div>
        <button
          type="button"
          onClick={() => setAutoScroll((current) => !current)}
          aria-pressed={autoScroll}
          className={`text-[11px] px-2 py-0.5 rounded ${autoScroll ? 'text-purple-300 bg-purple-950/60' : 'text-slate-500 hover:text-slate-300'}`}
        >
          Auto-scroll: {autoScroll ? 'ON' : 'OFF'}
        </button>
      </div>
    </div>
  );
}
