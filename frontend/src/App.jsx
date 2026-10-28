import React, { useState, useEffect } from 'react';
import {
  Bot,
  Terminal,
  FileCode,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Sparkles,
  ShieldCheck,
  Bug,
  Activity,
  Layers,
  ArrowRight,
  ExternalLink,
  Info
} from 'lucide-react';
import CodeInput from './components/CodeInput';
import AgentLogs from './components/AgentLogs';
import TestViewer from './components/TestViewer';
import { generateAndTestApi, SAMPLE_PRESETS } from './services/api';

export default function App() {
  // Core states: 'idle' | 'loading' | 'success' | 'defect_detected'
  const [status, setStatus] = useState('idle');
  const [activeTab, setActiveTab] = useState('logs'); // 'logs' | 'suite'
  const [code, setCode] = useState(SAMPLE_PRESETS[0].code);
  const [activePresetId, setActivePresetId] = useState(SAMPLE_PRESETS[0].id);

  // Agent output data
  const [logs, setLogs] = useState([]);
  const [generatedTestCode, setGeneratedTestCode] = useState('');
  const [defectDetails, setDefectDetails] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  // Switch preset
  const handleSelectPreset = (presetId) => {
    const preset = SAMPLE_PRESETS.find((p) => p.id === presetId);
    if (preset) {
      setCode(preset.code);
      setActivePresetId(preset.id);
      setStatus('idle');
      setErrorMessage(null);
      setDefectDetails(null);
    }
  };

  // Main generation & execution orchestrator
  const handleGenerateAndTest = async () => {
    if (!code || code.trim().length === 0) return;

    setStatus('loading');
    setErrorMessage(null);
    setDefectDetails(null);
    setActiveTab('logs'); // Switch to terminal logs to watch execution
    setLogs([
      `[${new Date().toLocaleTimeString('en-US', { hour12: false })}] [INFO] Initializing TestForge Autonomous Agent...`,
      `[${new Date().toLocaleTimeString('en-US', { hour12: false })}] [AGENT] Connecting to isolated sandbox environment...`
    ]);

    try {
      // Call the REAL Axios POST request via the API service
      const result = await generateAndTestApi(code);

      // Stream the logs into terminal in timed stages for visual feedback
      const allLogs = result.logs || [];
      const intermediateDelay = 120;

      for (let i = 2; i < allLogs.length; i++) {
        await new Promise((resolve) => setTimeout(resolve, intermediateDelay));
        setLogs((prev) => [...prev, allLogs[i]]);
      }

      setGeneratedTestCode(result.code);
      setMetrics(result.metrics);

      if (result.defect_detected) {
        setStatus('defect_detected');
        setDefectDetails(result.defectDetails);
      } else {
        setStatus('success');
      }
    } catch (err) {
      console.error('TestForge execution error:', err);
      setStatus('defect_detected');
      setErrorMessage(err.message || 'An error occurred during test synthesis.');
      setLogs((prev) => [
        ...prev,
        `[${new Date().toLocaleTimeString('en-US', { hour12: false })}] [WARN] Network or synthesis exception: ${err.message}`
      ]);
    }
  };

  // Reset to initial state
  const handleReset = () => {
    setStatus('idle');
    setLogs([]);
    setGeneratedTestCode('');
    setDefectDetails(null);
    setMetrics(null);
    setErrorMessage(null);
    setActiveTab('logs');
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col font-sans antialiased selection:bg-purple-100 selection:text-purple-900">
      {/* Top Navbar */}
      <header className="sticky top-0 z-30 bg-white border-b border-slate-200 shadow-xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          {/* Left: Brand & Badges */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-600 flex items-center justify-center text-white shadow-sm shadow-purple-200">
              <Bot className="w-5 h-5" />
            </div>

            <div className="flex items-center gap-2.5">
              <span className="text-lg font-bold text-slate-900 tracking-tight">
                TestForge <span className="text-purple-600">AI</span>
              </span>

              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-50 text-purple-700 border border-purple-200/80">
                <span className="w-1.5 h-1.5 rounded-full bg-purple-600" />
                Autonomous QA Agent
              </span>
            </div>
          </div>

          {/* Center / Right: Engine Status & Presets */}
          <div className="flex items-center gap-3">
            {/* Quick Presets Toggle Pills */}
            <div className="hidden md:flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg border border-slate-200/80 text-xs">
              <span className="px-2 text-slate-500 font-medium">Quick Demo:</span>
              <button
                type="button"
                onClick={() => handleSelectPreset('auth_clean')}
                className={`px-2.5 py-1 rounded-md font-medium transition-all cursor-pointer ${
                  activePresetId === 'auth_clean'
                    ? 'bg-white text-purple-700 shadow-xs border border-slate-200/80'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-white/50'
                }`}
              >
                Auth Route (Clean)
              </button>
              <button
                type="button"
                onClick={() => handleSelectPreset('checkout_defect')}
                className={`px-2.5 py-1 rounded-md font-medium transition-all cursor-pointer ${
                  activePresetId === 'checkout_defect'
                    ? 'bg-white text-rose-700 shadow-xs border border-slate-200/80'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-white/50'
                }`}
              >
                Checkout (Defect)
              </button>
            </div>

            {/* Current Lifecycle Status Pill */}
            <div className="hidden sm:inline-flex items-center gap-2 px-3 py-1 rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-700">
              <span className="text-slate-400">Status:</span>
              {status === 'idle' && (
                <span className="text-slate-500 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-slate-400" />
                  Idle
                </span>
              )}
              {status === 'loading' && (
                <span className="text-purple-600 flex items-center gap-1.5 font-semibold">
                  <span className="w-2 h-2 rounded-full bg-purple-600 animate-ping" />
                  Synthesizing
                </span>
              )}
              {status === 'success' && (
                <span className="text-emerald-600 flex items-center gap-1.5 font-semibold">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  Passed (100%)
                </span>
              )}
              {status === 'defect_detected' && (
                <span className="text-rose-600 flex items-center gap-1.5 font-semibold">
                  <span className="w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
                  Defect Flagged
                </span>
              )}
            </div>

            <button
              type="button"
              onClick={handleReset}
              title="Reset session"
              aria-label="Reset session"
              className="p-2 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer border border-transparent hover:border-slate-200"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col gap-5">
        {/* Core State Notification Banners */}
        {status === 'idle' && (
          <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-purple-50 text-purple-600 flex items-center justify-center shrink-0 border border-purple-100">
                <Sparkles className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-slate-900">
                  Ready to Synthesize &amp; Self-Heal API Tests
                </h3>
                <p className="text-xs text-slate-600 mt-0.5">
                  Paste your FastAPI route definitions or choose a pre-configured template. TestForge AI will extract AST contracts, generate pytest suites, and isolate regressions.
                </p>
              </div>
            </div>
            <div className="hidden md:flex items-center gap-2 text-xs font-mono text-purple-700 bg-purple-50 px-3 py-1.5 rounded-lg border border-purple-200/70 shrink-0">
              <span>Engine: pytest 8.x + TestClient</span>
            </div>
          </div>
        )}

        {status === 'loading' && (
          <div className="bg-purple-50/70 border border-purple-200 rounded-xl p-4 shadow-xs flex items-center justify-between gap-4 animate-pulse">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-purple-600 text-white flex items-center justify-center shrink-0">
                <Activity className="w-5 h-5 animate-spin" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-purple-950 flex items-center gap-2">
                  <span>Autonomous QA Agent in Progress...</span>
                  <span className="text-xs font-mono font-normal text-purple-700 bg-purple-100 px-2 py-0.5 rounded-full">
                    Step 3/4: Self-Healing &amp; Verification
                  </span>
                </h3>
                <p className="text-xs text-purple-800/80 mt-0.5">
                  Fuzzing boundary inputs, testing status code contracts, and applying automated fixture repairs...
                </p>
              </div>
            </div>
          </div>
        )}

        {status === 'success' && (
          <div className="bg-emerald-50 border border-emerald-200/90 rounded-xl p-4 shadow-xs flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-lg bg-emerald-600 text-white flex items-center justify-center shrink-0 shadow-xs">
                <CheckCircle2 className="w-5 h-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-semibold text-emerald-950">
                    Autonomous Test Suite Generated &amp; Verified
                  </h3>
                  <span className="text-[11px] font-semibold bg-emerald-100 text-emerald-800 px-2 py-0.5 rounded-full border border-emerald-200">
                    100% Passed
                  </span>
                </div>
                <p className="text-xs text-emerald-800/90 mt-0.5">
                  All assertions satisfied in sandboxed pytest container. Automatic fixture repair reconciled client lifespan and boundary mutations.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setActiveTab('suite')}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs transition-colors cursor-pointer"
              >
                <span>View test_app.py</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}

        {status === 'defect_detected' && (
          <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 sm:p-5 shadow-xs flex flex-col gap-3.5 transition-all">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-start gap-3">
                <div className="w-9 h-9 rounded-lg bg-rose-600 text-white flex items-center justify-center shrink-0 shadow-xs">
                  <AlertTriangle className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-bold text-rose-950">
                      Defect Detected: Unhandled Source Bug in FastAPI Route!
                    </h3>
                    <span className="text-[11px] font-semibold bg-rose-200/80 text-rose-900 px-2 py-0.5 rounded-full border border-rose-300">
                      CRITICAL 500 BUG
                    </span>
                  </div>
                  <p className="text-xs text-rose-900/90 mt-1 leading-relaxed">
                    {defectDetails?.message || errorMessage || 'The autonomous fuzzer discovered an edge condition that crashes the endpoint with an unhandled 500 error.'}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => setActiveTab('suite')}
                className="self-start sm:self-auto shrink-0 inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white shadow-xs transition-colors cursor-pointer"
              >
                <span>Inspect Repro Test</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Defect diagnostic metadata */}
            {defectDetails && (
              <div className="bg-white/90 border border-rose-200/80 rounded-lg p-3 sm:p-3.5 text-xs flex flex-col gap-2">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 font-mono text-[11px] text-rose-900">
                  <div className="bg-rose-50/60 p-2 rounded border border-rose-100">
                    <span className="text-rose-500 font-bold block mb-0.5">DEFECT TYPE</span>
                    <span>{defectDetails.type}</span>
                  </div>
                  <div className="bg-rose-50/60 p-2 rounded border border-rose-100">
                    <span className="text-rose-500 font-bold block mb-0.5">LOCATION</span>
                    <span>{defectDetails.location}</span>
                  </div>
                </div>
                <div className="text-slate-800 pt-1 border-t border-rose-100">
                  <span className="font-semibold text-rose-900">AI Recommendation:</span>{' '}
                  <code className="font-mono text-[11px] bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded border border-slate-200">
                    {defectDetails.recommendation}
                  </code>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Main Content Split Screen (Grid 12 cols: 6 Left, 6 Right) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch flex-1">
          {/* Left Panel: Raw FastAPI Route Code Input */}
          <div className="lg:col-span-6 flex flex-col">
            <CodeInput
              code={code}
              onChange={setCode}
              onGenerate={handleGenerateAndTest}
              status={status}
              onSelectPreset={handleSelectPreset}
              activePresetId={activePresetId}
            />
          </div>

          {/* Right Panel: Output with Tabbed Interface */}
          <div className="lg:col-span-6 flex flex-col">
            <section 
              aria-label="Agent Output and Test Suite" 
              className="bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col h-[520px] lg:h-[560px] overflow-hidden"
            >
              {/* Tabbed Navigation Bar */}
              <div className="px-5 border-b border-slate-200 flex items-center justify-between bg-white">
                <nav className="flex items-center gap-6" aria-label="Output views">
                  {/* Tab 1: Agent Logs (Default) */}
                  <button
                    type="button"
                    onClick={() => setActiveTab('logs')}
                    className={`py-3.5 text-xs sm:text-sm font-medium border-b-2 flex items-center gap-2 transition-all cursor-pointer ${
                      activeTab === 'logs'
                        ? 'border-purple-600 text-purple-600 font-semibold'
                        : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <Terminal className="w-4 h-4" />
                    <span>Agent Logs</span>
                    {logs.length > 0 && (
                      <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full ${
                        activeTab === 'logs' ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-500'
                      }`}>
                        {logs.length}
                      </span>
                    )}
                  </button>

                  {/* Tab 2: Generated Suite */}
                  <button
                    type="button"
                    onClick={() => setActiveTab('suite')}
                    className={`py-3.5 text-xs sm:text-sm font-medium border-b-2 flex items-center gap-2 transition-all cursor-pointer ${
                      activeTab === 'suite'
                        ? 'border-purple-600 text-purple-600 font-semibold'
                        : 'border-transparent text-slate-500 hover:text-slate-800'
                    }`}
                  >
                    <FileCode className="w-4 h-4" />
                    <span>Generated Suite</span>
                    {generatedTestCode && (
                      <span className={`text-[10px] font-mono px-1.5 py-0.2 rounded-full ${
                        activeTab === 'suite' ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-500'
                      }`}>
                        test_app.py
                      </span>
                    )}
                  </button>
                </nav>

                {/* Tab auxiliary info */}
                <div className="hidden sm:flex items-center gap-2 text-xs text-slate-400">
                  {activeTab === 'logs' ? (
                    <span className="font-mono text-[11px]">sandbox: pytest isolate</span>
                  ) : (
                    <span className="font-mono text-[11px]">syntax: python</span>
                  )}
                </div>
              </div>

              {/* Tab Panel Content */}
              <div className="flex-1 flex flex-col overflow-hidden">
                {activeTab === 'logs' ? (
                  <AgentLogs
                    logs={logs}
                    status={status}
                    metrics={metrics}
                    defectDetails={defectDetails}
                    onReset={handleReset}
                  />
                ) : (
                  <TestViewer
                    code={generatedTestCode}
                    status={status}
                    metrics={metrics}
                    defectDetails={defectDetails}
                  />
                )}
              </div>
            </section>
          </div>
        </div>
      </main>

      {/* Enterprise SaaS Footer */}
      <footer className="mt-auto bg-white border-t border-slate-200 py-3.5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-500">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-800">TestForge AI</span>
            <span>&mdash; Autonomous API test-generation &amp; repair engine</span>
          </div>
          <div className="flex items-center gap-4 text-slate-400">
            <span>FastAPI 0.110+</span>
            <span>•</span>
            <span>Pytest 8.x</span>
            <span>•</span>
            <span>Autonomous Healing Active</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
