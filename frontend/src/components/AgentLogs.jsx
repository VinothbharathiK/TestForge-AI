import React, { useState, useEffect, useRef } from 'react';
import {
  Terminal,
  Copy,
  Check,
  RotateCcw,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Clock,
  Sparkles,
  ArrowDown
} from 'lucide-react';

/**
 * Terminal-like execution window for TestForge Autonomous QA Agent.
 * High-contrast dark styling (bg-slate-900) even in light mode.
 */
export default function AgentLogs({
  logs = [],
  status,
  metrics,
  defectDetails,
  onReset
}) {
  const [copied, setCopied] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const logContainerRef = useRef(null);

  const isLoading = status === 'loading';
  const isDefect = status === 'defect_detected';
  const isSuccess = status === 'success';
  const isIdle = status === 'idle';

  // Auto-scroll to bottom as logs update
  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, isLoading, autoScroll]);

  const handleCopyLogs = async () => {
    try {
      const fullLogText = logs.join('\n');
      await navigator.clipboard.writeText(fullLogText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error('Failed to copy logs', e);
    }
  };

  // Helper to colorize log prefixes
  const renderLogLine = (line, idx) => {
    let colorClass = 'text-slate-300';
    let badgeClass = 'text-slate-400';

    if (line.includes('[SUCCESS]')) {
      colorClass = 'text-emerald-400 font-medium';
      badgeClass = 'text-emerald-300 font-bold';
    } else if (line.includes('[DEFECT]') || line.includes('[WARN]')) {
      colorClass = 'text-rose-400 font-medium';
      badgeClass = 'text-rose-300 font-bold';
    } else if (line.includes('[HEAL]')) {
      colorClass = 'text-amber-300 font-medium';
      badgeClass = 'text-amber-400 font-bold';
    } else if (line.includes('[AGENT]') || line.includes('[SYNTH]')) {
      colorClass = 'text-purple-300';
      badgeClass = 'text-purple-400 font-bold';
    } else if (line.includes('[EXEC]')) {
      colorClass = 'text-sky-300';
      badgeClass = 'text-sky-400';
    } else if (line.includes('[INFO]')) {
      colorClass = 'text-slate-400';
      badgeClass = 'text-cyan-400';
    }

    return (
      <div key={idx} className={`leading-6 flex items-start gap-2 font-mono text-xs sm:text-[13px] ${colorClass}`}>
        <span className="select-none text-slate-600 text-[11px] w-6 text-right shrink-0">
          {idx + 1}
        </span>
        <span className="break-all whitespace-pre-wrap">{line}</span>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 rounded-b-xl overflow-hidden text-slate-200">
      {/* Terminal Titlebar Chrome */}
      <div className="px-4 py-3 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between text-xs select-none">
        {/* Left: macOS-style window dots & Shell status */}
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

        {/* Right: State badge & Terminal actions */}
        <div className="flex items-center gap-2">
          {isLoading && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-purple-900/60 text-purple-300 border border-purple-700/50 animate-pulse">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-400" />
              HEALING_LOOP
            </span>
          )}

          {isSuccess && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-emerald-900/60 text-emerald-300 border border-emerald-700/50">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              SANDBOX_PASS
            </span>
          )}

          {isDefect && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-rose-900/60 text-rose-300 border border-rose-700/50">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
              DEFECT_HALTED
            </span>
          )}

          {logs.length > 0 && (
            <button
              type="button"
              onClick={handleCopyLogs}
              title="Copy terminal logs"
              aria-label="Copy terminal logs"
              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-mono transition-colors cursor-pointer border border-slate-700"
            >
              {copied ? (
                <>
                  <Check className="w-3 h-3 text-emerald-400" />
                  <span>Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3 text-slate-400" />
                  <span>Copy</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Terminal Log Output Stream */}
      <div 
        ref={logContainerRef}
        role="log"
        aria-live="polite"
        className="flex-1 min-h-0 p-4 overflow-y-auto space-y-1 font-mono scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-900"
      >
        {isIdle && logs.length === 0 && (
          <div className="h-full min-h-[300px] flex flex-col items-center justify-center text-center text-slate-500 py-12">
            <Cpu className="w-10 h-10 text-slate-700 mb-3" />
            <p className="font-mono text-sm text-slate-400 mb-1">
              TestForge Autonomous Agent: Standing By
            </p>
            <p className="text-xs text-slate-600 max-w-sm mb-4">
              Click &quot;Generate &amp; Test&quot; to compile your FastAPI routes, synthesize property tests, and run isolated pytest sandbox verification.
            </p>
            <div className="text-[11px] font-mono text-slate-600 bg-slate-950/60 px-3 py-1.5 rounded border border-slate-800">
              $ testforge --watch --auto-heal --fuzz
            </div>
          </div>
        )}

        {/* Render all log entries */}
        {logs.map((line, idx) => renderLogLine(line, idx))}

        {/* Pulsing loading state in the terminal log */}
        {isLoading && (
          <div className="pt-2 pb-3 space-y-2 border-t border-slate-800/80 mt-2">
            <div className="flex items-center gap-2 text-purple-400 text-xs font-mono animate-pulse">
              <span className="w-2 h-2 rounded-full bg-purple-400 inline-block" />
              <span>Agent active: Drafting test suite and executing isolated pytest sandbox...</span>
            </div>
            <div className="text-amber-400/90 text-xs font-mono pl-4 animate-pulse">
              &gt; Evaluating boundary conditions &amp; self-healing fixture dependencies...
            </div>
          </div>
        )}

        {/* Terminal bottom prompt cursor */}
        <div className="flex items-center gap-2 text-slate-500 text-xs pt-2">
          <span className="text-purple-400 font-bold">$</span>
          <span className="inline-block w-2 h-4 bg-green-400 animate-pulse" />
        </div>
      </div>

      {/* Terminal Footer Bar with Metrics */}
      <div className="px-4 py-2.5 bg-slate-950 border-t border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400 font-mono">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-slate-500" />
            Sandbox: {metrics?.executionTimeMs ? `${metrics.executionTimeMs}ms` : '--'}
          </span>
          <span className="text-slate-700">|</span>
          <span>
            Assertions: {metrics?.totalAssertions ? `${metrics.totalAssertions} passed` : '--'}
          </span>
          <span className="text-slate-700">|</span>
          <span>
            Coverage: {metrics?.coveragePct ? `${metrics.coveragePct}%` : '--'}
          </span>
        </div>

        <button
          type="button"
          onClick={() => setAutoScroll(!autoScroll)}
          className={`text-[11px] px-2 py-0.5 rounded transition-colors cursor-pointer ${
            autoScroll ? 'text-purple-300 bg-purple-950/60' : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          Auto-scroll: {autoScroll ? 'ON' : 'OFF'}
        </button>
      </div>
    </div>
  );
}
