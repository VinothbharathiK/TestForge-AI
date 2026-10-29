import React, { useMemo } from 'react';
import {
  Code2,
  Play,
  RotateCcw,
  Sparkles,
  FileCode2,
  Trash2,
  Loader2,
  Bug,
  ShieldCheck,
  ChevronDown
} from 'lucide-react';
import { SAMPLE_PRESETS } from '../services/api';

/**
 * Left panel editor component for raw FastAPI route definitions.
 */
export default function CodeInput({
  code,
  onChange,
  onGenerate,
  status,
  onSelectPreset,
  activePresetId
}) {
  const isLoading = status === 'loading';

  // Compute live statistics on the user's input
  const stats = useMemo(() => {
    const lines = (code || '').split('\n');
    const totalLines = lines.length;
    const charCount = (code || '').length;

    // Fast regex for detected endpoints
    const matches = (code || '').match(/@(app|router)\.(get|post|put|delete|patch)\s*\(/gi) || [];
    const routeCount = matches.length;

    return { totalLines, charCount, routeCount };
  }, [code]);

  // Handle Ctrl+Enter / Cmd+Enter to run
  const handleKeyDown = (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      if (!isLoading && code.trim().length > 0) {
        e.preventDefault();
        onGenerate();
      }
    }
  };

  const handleClear = () => {
    onChange('');
  };

  const gutterRef = React.useRef(null);

  // Sync line number gutter with textarea scroll
  const handleScroll = (e) => {
    if (gutterRef.current) {
      gutterRef.current.scrollTop = e.target.scrollTop;
    }
  };

  return (
    <section 
      aria-label="FastAPI Route Input" 
      className="tf-workbench-panel flex-1 bg-white rounded-xl shadow-sm border border-slate-200 transition-colors duration-200"
    >
      {/* Panel Header */}
      <div className="px-5 py-3.5 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 bg-white shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center border border-purple-100">
            <Code2 className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-900 tracking-tight">
                FastAPI Route Definition
              </h2>
              <span className="text-xs font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full border border-slate-200">
                Python 3.11+
              </span>
            </div>
            <p className="text-[13px] text-slate-500 mt-0.5">
              Paste ASGI router, endpoints, or Pydantic models below
            </p>
          </div>
        </div>

        {/* Preset Selector */}
        <div className="flex items-center gap-2">
          <div className="relative group">
            <label htmlFor="sample-preset-select" className="sr-only">
              Load sample FastAPI route
            </label>
            <div className="relative inline-flex items-center">
              <select
                id="sample-preset-select"
                aria-label="Load sample FastAPI route"
                className="appearance-none text-[13px] font-medium bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-700 pl-3 pr-8 py-1.5 rounded-lg transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500"
                value={activePresetId || ''}
                onChange={(e) => onSelectPreset(e.target.value)}
                disabled={isLoading}
              >
                <option value="" disabled>Load Sample Route...</option>
                {SAMPLE_PRESETS.map((preset) => (
                  <option key={preset.id} value={preset.id}>
                    {preset.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 pointer-events-none" />
            </div>
          </div>

          <button
            type="button"
            onClick={handleClear}
            disabled={isLoading || !code}
            title="Clear editor"
            aria-label="Clear code editor"
            className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg border border-transparent hover:border-rose-200 transition-colors disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-slate-400 cursor-pointer disabled:cursor-not-allowed"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Editor & Line Numbers (Scrollable flex area) */}
      <div className="relative flex-1 min-h-0 flex overflow-hidden bg-slate-50 border-b border-slate-200">
        {/* Simple line counter gutter */}
        <div 
          ref={gutterRef}
          aria-hidden="true" 
          className="select-none py-3.5 px-3 bg-slate-100/70 border-r border-slate-200 text-right text-xs font-mono text-slate-400 min-w-[44px] overflow-hidden"
        >
          {Array.from({ length: Math.max(stats.totalLines, 16) }).map((_, i) => (
            <div key={i} className="leading-6">
              {i + 1}
            </div>
          ))}
        </div>

        {/* Textarea Code Input */}
        <div className="relative flex-1 flex flex-col min-h-0">
          <label htmlFor="fastapi-code-editor" className="sr-only">
            FastAPI Route Python Code
          </label>
          <textarea
            id="fastapi-code-editor"
            value={code}
            onChange={(e) => onChange(e.target.value)}
            onScroll={handleScroll}
            onKeyDown={handleKeyDown}
            placeholder={`# Paste your FastAPI endpoint code here...\n\nfrom fastapi import FastAPI\napp = FastAPI()\n\n@app.get("/items/{item_id}")\ndef read_item(item_id: int):\n    return {"item_id": item_id, "status": "active"}`}
            spellCheck={false}
            disabled={isLoading}
            className="w-full flex-1 p-3.5 font-mono text-[13px] sm:text-sm leading-6 text-slate-800 bg-transparent resize-none border-0 focus:outline-none focus:ring-0 placeholder:text-slate-400 font-normal overflow-y-auto"
            style={{ tabSize: 4 }}
          />

          {/* Quick preset pills if empty */}
          {(!code || code.trim().length === 0) && (
            <div className="absolute inset-0 m-6 flex flex-col items-center justify-center pointer-events-none text-center">
              <FileCode2 className="w-10 h-10 text-slate-300 mb-2" />
              <p className="text-sm font-medium text-slate-600 mb-1">
                Editor is empty
              </p>
              <p className="text-[13px] text-slate-400 max-w-xs mb-3">
                Paste your FastAPI routes or choose a pre-configured scenario to test:
              </p>
              <div className="flex flex-wrap gap-2 pointer-events-auto">
                <button
                  type="button"
                  onClick={() => onSelectPreset('auth-clean')}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium bg-white hover:bg-purple-50 text-slate-700 hover:text-purple-700 border border-slate-200 hover:border-purple-200 shadow-xs transition-colors cursor-pointer"
                >
                  <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                  Load Auth API (Clean)
                </button>
                <button
                  type="button"
                  onClick={() => onSelectPreset('checkout-defect')}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium bg-white hover:bg-rose-50 text-slate-700 hover:text-rose-700 border border-slate-200 hover:border-rose-200 shadow-xs transition-colors cursor-pointer"
                >
                  <Bug className="w-3.5 h-3.5 text-rose-500" />
                  Load Buggy Route (Defect)
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Editor Footer & Action Button */}
      <div className="p-4 bg-white flex flex-col gap-3">
        {/* Real-time stats bar */}
        <div className="flex items-center justify-between text-[13px] text-slate-500">
          <div className="flex items-center gap-3">
            <span>
              <strong className="text-slate-700 font-medium">{stats.routeCount}</strong> {stats.routeCount === 1 ? 'route' : 'routes'} detected
            </span>
            <span className="text-slate-300">•</span>
            <span>
              <strong className="text-slate-700 font-medium">{stats.totalLines}</strong> lines
            </span>
            <span className="text-slate-300">•</span>
            <span>
              <strong className="text-slate-700 font-medium">{stats.charCount}</strong> chars
            </span>
          </div>

          <div className="hidden sm:flex items-center gap-1 text-[13px] text-slate-400">
            <kbd className="px-1.5 py-0.5 bg-slate-100 rounded text-slate-500 border border-slate-200 font-mono text-xs">
              ⌘/Ctrl + Enter
            </kbd>
            <span>to run</span>
          </div>
        </div>

        {/* Prominent Full-Width Purple "Generate & Test" Button */}
        <button
          type="button"
          onClick={onGenerate}
          disabled={isLoading || !code || code.trim().length === 0}
          className="w-full bg-purple-600 hover:bg-purple-700 active:bg-purple-800 text-white text-[14px] font-semibold py-3 px-4 rounded-xl shadow-sm hover:shadow-md transition-all duration-150 flex items-center justify-center gap-2.5 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer focus:outline-none focus:ring-4 focus:ring-purple-500/20"
        >
          {isLoading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-purple-200" />
              <span>Synthesizing & Sandboxing Suite...</span>
            </>
          ) : (
            <>
              <Sparkles className="w-4 h-4 text-purple-200" />
              <span>Generate & Test</span>
            </>
          )}
        </button>
      </div>
    </section>
  );
}
