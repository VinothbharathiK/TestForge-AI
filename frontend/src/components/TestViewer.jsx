import React, { useState } from 'react';
import {
  FileCode2,
  Copy,
  Check,
  Download,
  CheckCircle2,
  AlertCircle,
  FileCheck,
  Sparkles,
  ShieldAlert
} from 'lucide-react';

/**
 * Light-mode code viewer for the final synthesized 'test_app.py' test suite.
 */
export default function TestViewer({
  code,
  status,
  metrics,
  defectDetails
}) {
  const [copied, setCopied] = useState(false);

  const isSuccess = status === 'success';
  const isDefect = status === 'defect_detected';

  const handleCopy = async () => {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e) {
      console.error('Failed to copy code', e);
    }
  };

  const handleDownload = () => {
    if (!code) return;
    const blob = new Blob([code], { type: 'text/x-python;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'test_app.py';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Syntax highlighting for Python in light mode
  const renderHighlightedLine = (line) => {
    // Escape standard tags
    if (line.trim().startsWith('#')) {
      return <span className="text-slate-400 italic">{line}</span>;
    }
    if (line.trim().startsWith('"""') || line.trim().startsWith("'''") || line.includes('"""')) {
      return <span className="text-slate-500 font-medium">{line}</span>;
    }

    // Decorators like @app.get, @pytest.fixture
    if (line.trim().startsWith('@')) {
      return <span className="text-amber-700 font-semibold">{line}</span>;
    }

    // Replace keywords, strings, function names
    const parts = [];
    const tokens = line.split(/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:def|import|from|return|assert|with|as|yield|class|if|else|elif|for|in|is|not|try|except|raise|None|True|False)\b)/g);

    return (
      <span>
        {tokens.map((token, i) => {
          if (!token) return null;
          if (token.startsWith('"') || token.startsWith("'")) {
            return <span key={i} className="text-emerald-700">{token}</span>;
          }
          if (/^(def|class)$/.test(token)) {
            return <span key={i} className="text-purple-700 font-semibold">{token}</span>;
          }
          if (/^(import|from|as|with|yield|assert|return|raise|try|except)$/.test(token)) {
            return <span key={i} className="text-indigo-600 font-semibold">{token}</span>;
          }
          if (/^(if|else|elif|for|in|is|not)$/.test(token)) {
            return <span key={i} className="text-rose-600 font-medium">{token}</span>;
          }
          if (/^(True|False|None)$/.test(token)) {
            return <span key={i} className="text-amber-600 font-semibold">{token}</span>;
          }
          return <span key={i} className="text-slate-800">{token}</span>;
        })}
      </span>
    );
  };

  const lines = (code || '').split('\n');

  if (!code) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-12 text-center bg-slate-50 rounded-b-xl border border-dashed border-slate-200">
        <FileCode2 className="w-12 h-12 text-slate-300 mb-3" />
        <h3 className="text-sm font-semibold text-slate-700 mb-1">
          No Test Suite Generated Yet
        </h3>
        <p className="text-[13px] text-slate-500 max-w-sm mb-4">
          Paste your FastAPI route definition on the left and click &quot;Generate &amp; Test&quot; to inspect the generated test suite.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-b-xl overflow-hidden">
      {/* Test Suite Summary Banner */}
      <div className="px-5 py-3.5 bg-slate-50 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 text-[13px]">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 font-mono font-medium text-slate-800">
            <FileCode2 className="w-4 h-4 text-purple-600" />
            <span>test_app.py</span>
          </div>

          <span className="text-slate-300">|</span>

          <span className="text-slate-600">
            Framework: <strong className="text-slate-900 font-semibold">pytest + TestClient</strong>
          </span>

          {metrics?.healedFixtures > 0 && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-800 border border-amber-200">
              <Sparkles className="w-3 h-3 text-amber-500" />
              1 Fixture Self-Healed
            </span>
          )}

          {isDefect && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-50 text-rose-800 border border-rose-200">
              <ShieldAlert className="w-3 h-3 text-rose-500" />
              Defect Repro Included
            </span>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium text-slate-700 bg-white hover:bg-slate-100 border border-slate-200 shadow-xs transition-colors cursor-pointer"
          >
            {copied ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-emerald-700">Copied</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5 text-slate-500" />
                <span>Copy Code</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleDownload}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 shadow-xs transition-colors cursor-pointer"
          >
            <Download className="w-3.5 h-3.5 text-purple-600" />
            <span>Download test_app.py</span>
          </button>
        </div>
      </div>

      {/* Code Viewer Container */}
      <div className="flex-1 min-h-0 overflow-auto bg-slate-50 flex font-mono text-[13px] sm:text-sm border-b border-slate-200">
        {/* Line Numbers */}
        <div 
          aria-hidden="true" 
          className="select-none py-3.5 px-3 bg-slate-100/60 border-r border-slate-200 text-right text-slate-400 min-w-[44px]"
        >
          {lines.map((_, i) => (
            <div key={i} className="leading-6">
              {i + 1}
            </div>
          ))}
        </div>

        {/* Code Lines */}
        <div className="flex-1 p-3.5 overflow-x-auto">
          {lines.map((line, i) => (
            <div key={i} className="leading-6 whitespace-pre font-mono">
              {renderHighlightedLine(line)}
            </div>
          ))}
        </div>
      </div>

      {/* Test Metrics Footer */}
      <div className="px-5 py-3 bg-white flex flex-wrap items-center justify-between gap-3 text-[13px] text-slate-500">
        <div className="flex items-center gap-2">
          <FileCheck className="w-4 h-4 text-emerald-600" />
          <span>Ready for CI/CD integration: Run with <code className="font-mono bg-slate-100 text-slate-800 px-1 py-0.5 rounded text-xs">pytest -v</code></span>
        </div>

        <div className="flex items-center gap-3">
          <span>{lines.length} lines</span>
          <span className="text-slate-300">•</span>
          <span>UTF-8 Python 3</span>
        </div>
      </div>
    </div>
  );
}
