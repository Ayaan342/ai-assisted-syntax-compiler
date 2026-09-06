import { useEffect, useRef, useState } from "react";
import { FileCode, X, ArrowRight } from "@phosphor-icons/react";
import { Toolbar } from "./components/Toolbar";
import { CodeEditor, type EditorHandle } from "./components/CodeEditor";
import { AnalysisPanel } from "./components/AnalysisPanel";
import { DiagnosticList } from "./components/DiagnosticList";
import { InspectorTabs, tabs, type Tab } from "./components/InspectorTabs";
import { ASTView } from "./components/ASTView";
import { SymbolTableView } from "./components/SymbolTableView";
import { TokenTable } from "./components/TokenTable";
import { CorrectionPanel } from "./components/CorrectionPanel";
import { DEFAULT_CODE } from "./constants/examples";
import {
  analyzeCode,
  checkHealth,
  correctCode,
  getTokens,
} from "./services/api";
import type {
  AnalysisResponse,
  CorrectionResponse,
  Diagnostic,
  Health,
  Token,
} from "./types/compiler";

export default function App() {
  const [code, setCode] = useState(DEFAULT_CODE);
  const [health, setHealth] = useState<Health | null>(null);
  const [checking, setChecking] = useState(true);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [correction, setCorrection] = useState<CorrectionResponse | null>(null);
  const [tokens, setTokens] = useState<Token[] | null>(null);
  const [active, setActive] = useState<Tab>("Diagnostics");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("Ready to analyze");
  const [selected, setSelected] = useState<Diagnostic | null>(null);
  const editor = useRef<EditorHandle | null>(null);
  const current = useRef(DEFAULT_CODE);
  const task = useRef<AbortController | null>(null);
  const tokenTask = useRef<AbortController | null>(null);
  const healthTask = useRef<AbortController | null>(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const diagnostics = analysis
    ? [
        ...analysis.lexical.errors,
        ...analysis.syntax.errors,
        ...analysis.semantic.errors,
      ]
    : [];
  async function refreshHealth() {
    healthTask.current?.abort();
    const controller = new AbortController();
    healthTask.current = controller;
    setChecking(true);
    try {
      const result = await checkHealth(controller.signal);
      if (!controller.signal.aborted) setHealth(result);
    } catch {
      if (!controller.signal.aborted) setHealth(null);
    } finally {
      if (!controller.signal.aborted) setChecking(false);
    }
  }
  useEffect(() => {
    void refreshHealth();
    return () => {
      task.current?.abort();
      tokenTask.current?.abort();
      healthTask.current?.abort();
    };
  }, []);
  function changeSource(value: string) {
    task.current?.abort();
    tokenTask.current?.abort();
    setBusy(null);
    setTokenLoading(false);
    current.current = value;
    setCode(value);
    setAnalysis(null);
    setCorrection(null);
    setTokens(null);
    setSelected(null);
    setError(null);
    setNotice("Source changed. Analyze to refresh results.");
  }
  async function loadTokens() {
    tokenTask.current?.abort();
    const controller = new AbortController();
    tokenTask.current = controller;
    setTokenLoading(true);
    try {
      const result = await getTokens(current.current, controller.signal);
      if (!controller.signal.aborted) setTokens(result.tokens);
    } catch (err) {
      if (!controller.signal.aborted)
        setError(err instanceof Error ? err.message : "Token request failed.");
    } finally {
      if (!controller.signal.aborted) setTokenLoading(false);
    }
  }
  function selectTab(tab: Tab) {
    setActive(tab);
    if (tab === "Tokens" && !tokens) void loadTokens();
  }
  async function run(mode: "analyze" | "correct", source = current.current) {
    task.current?.abort();
    const controller = new AbortController();
    task.current = controller;
    setBusy(mode);
    setError(null);
    setAnalysis(null);
    setSelected(null);
    setCorrection(null);
    try {
      if (mode === "analyze") {
        const result = await analyzeCode(source, controller.signal);
        if (controller.signal.aborted) return;
        setAnalysis(result);
        setSelected(
          [
            ...result.lexical.errors,
            ...result.syntax.errors,
            ...result.semantic.errors,
          ][0] ?? null,
        );
        setNotice(
          result.success
            ? "Analysis complete. All checks passed."
            : "Analysis complete. Diagnostics available.",
        );
        setActive("Diagnostics");
      } else {
        // Analyze the original buffer for correctly positioned markers. Correction diagnostics
        // refer to a different source version and are shown only in the review editor.
        const [result, original] = await Promise.all([
          correctCode(source, controller.signal),
          analyzeCode(source, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setCorrection(result);
        setAnalysis(original);
        setSelected(result.history[0]?.original_error ?? null);
        setActive("Corrections");
        setNotice(
          result.corrected_code !== source
            ? "Correction ready for review. Source has not changed."
            : result.success
              ? "Source is already syntax-valid."
              : "No correction applied. Review the unresolved result.",
        );
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof Error ? err.message : "Request failed.");
        setNotice("Request did not complete.");
      }
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }
  function focusDiagnostic(d: Diagnostic) {
    setSelected(d);
    editor.current?.revealLineInCenter(d.line);
    editor.current?.setPosition({ lineNumber: d.line, column: d.column });
    editor.current?.focus();
  }
  function applyCorrection() {
    if (!correction || current.current !== correction.original_code) return;
    const value = correction.corrected_code;
    changeSource(value);
    void run("analyze", value);
  }
  return (
    <main className="app-shell">
      <Toolbar
        health={health}
        checking={checking}
        busy={busy}
        onAnalyze={() => void run("analyze")}
        onCorrect={() => void run("correct")}
        onReset={() => {
          changeSource(DEFAULT_CODE);
          setAnalysis(null);
          setCorrection(null);
          setTokens(null);
          setSelected(null);
          setNotice("Default example restored.");
        }}
        onRetry={() => void refreshHealth()}
      />
      <div className="workspace-heading">
        <div>
          <span className="section-label">WORKSPACE</span>
          <span className="workspace-name">Syntax, explained.</span>
        </div>
      </div>
      {error && (
        <div role="alert" className="error-banner">
          <span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss error">
            <X />
          </button>
        </div>
      )}
      <div className="workbench">
        <section className="editor-panel" aria-label="Source workspace">
          <div className="editor-heading">
            <span className="file-tab">
              <FileCode size={17} />
              main.mc
            </span>
            <span>
              Mini-C <ArrowRight size={12} /> backend analysis
            </span>
          </div>
          <div
            className="source-editor"
            onKeyDown={(event) => event.stopPropagation()}
          >
            <CodeEditor
              code={code}
              onChange={changeSource}
              diagnostics={diagnostics}
              onReady={(instance) => {
                editor.current = instance;
              }}
            />
          </div>
          <div className="editor-footer">
            <span>{code.split("\n").length} lines</span>
            <span>UTF-8</span>
            <span>Spaces: 4</span>
            <span className="editor-mode">Editing only</span>
          </div>
        </section>
        <AnalysisPanel
          analysis={analysis}
          correction={correction}
          selected={selected}
        />
      </div>
      <section className="inspector">
        <InspectorTabs
          active={active}
          onChange={selectTab}
          count={diagnostics.length}
        />
        <div
          className="inspector-body"
          id="inspector-content"
          role="tabpanel"
          aria-labelledby={`tab-${tabs.indexOf(active)}`}
          tabIndex={0}
        >
          {busy ? (
            <div className="empty loading">
              <strong>
                {busy === "correct"
                  ? "Requesting validated corrections…"
                  : "Analyzing source…"}
              </strong>
              <span>Waiting for the compiler backend</span>
            </div>
          ) : active === "Tokens" ? (
            tokenLoading ? (
              <div className="empty">Loading backend tokens…</div>
            ) : (
              <TokenTable tokens={tokens} />
            )
          ) : active === "AST" ? (
            <ASTView ast={analysis?.ast ?? null} />
          ) : active === "Symbol Table" ? (
            <SymbolTableView symbols={analysis?.symbols ?? null} />
          ) : active === "Corrections" ? (
            <CorrectionPanel result={correction} onApply={applyCorrection} />
          ) : (
            <DiagnosticList
              diagnostics={diagnostics}
              onSelect={focusDiagnostic}
              analyzed={!!analysis}
            />
          )}
        </div>
      </section>
      <footer className="statusbar">
        <span role="status" aria-live="polite">
          {notice}
        </span>
        <span>Mini-C language / Compiler Workbench</span>
      </footer>
    </main>
  );
}
