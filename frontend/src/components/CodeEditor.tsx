import { useEffect, useRef } from "react";
import Editor, { loader, type OnMount } from "@monaco-editor/react";
// Editor core plus a visual colorizer only. No language services are imported.
import * as monaco from "monaco-editor/editor/editor.api";
import "monaco-editor/languages/definitions/cpp/register";
// The hover widget renders messages attached to backend-owned markers. It does
// not register a language service or infer diagnostics in the browser.
import "monaco-editor/editor/contrib/hover/browser/hoverContribution";
import EditorWorker from "monaco-editor/editor/editor.worker?worker";
import type { Diagnostic } from "../types/compiler";

self.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });
monaco.editor.defineTheme("minic-dark", {
  base: "vs-dark",
  inherit: true,
  rules: [
    { token: "keyword", foreground: "B7A7DC" },
    { token: "number", foreground: "D9B783" },
    { token: "comment", foreground: "72807B" },
  ],
  colors: {
    "editor.background": "#151819",
    "editor.foreground": "#D7DEDB",
    "editorLineNumber.foreground": "#626D69",
    "editorLineNumber.activeForeground": "#B9C6BF",
    "editor.lineHighlightBackground": "#1B2120",
    "editor.selectionBackground": "#314940",
    "editorCursor.foreground": "#97D4B5",
    "editorIndentGuide.background1": "#252D29",
    "editorError.foreground": "#EAA097",
    "editorWarning.foreground": "#DCC58F",
  },
});
export type EditorHandle = monaco.editor.IStandaloneCodeEditor;
export function CodeEditor({
  code,
  onChange,
  diagnostics,
  onReady,
  readOnly = false,
}: {
  code: string;
  onChange?: (value: string) => void;
  diagnostics: Diagnostic[];
  onReady?: (editor: EditorHandle) => void;
  readOnly?: boolean;
}) {
  const editorRef = useRef<EditorHandle | null>(null);
  const markers = (editor: EditorHandle) => {
    const model = editor.getModel();
    if (!model) return;
    monaco.editor.setModelMarkers(
      model,
      "backend",
      diagnostics.map((d) => ({
        severity:
          d.severity === "warning"
            ? monaco.MarkerSeverity.Warning
            : monaco.MarkerSeverity.Error,
        message: d.message,
        code: d.code,
        source: `Mini-C backend / ${d.phase}`,
        startLineNumber: d.span.start.line,
        startColumn: d.span.start.column,
        endLineNumber: d.span.end.line,
        endColumn:
          d.span.end.line === d.span.start.line
            ? Math.max(d.span.end.column, d.span.start.column + 1)
            : d.span.end.column,
      })),
    );
  };
  useEffect(() => {
    if (editorRef.current) markers(editorRef.current);
  }, [diagnostics]);
  const onMount: OnMount = (editor) => {
    editorRef.current = editor;
    markers(editor);
    onReady?.(editor);
  };
  return (
    <Editor
      value={code}
      language="cpp"
      theme="minic-dark"
      onChange={(value) => onChange?.(value ?? "")}
      onMount={onMount}
      loading={<div className="empty">Loading code editor…</div>}
      options={{
        readOnly,
        ariaLabel: readOnly
          ? "Corrected source preview"
          : "Mini-C source editor",
        automaticLayout: true,
        fontFamily: "Geist Mono, Consolas, monospace",
        fontSize: 14,
        lineHeight: 25,
        padding: { top: 22, bottom: 20 },
        tabSize: 4,
        insertSpaces: true,
        lineNumbers: "on",
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        overviewRulerLanes: 0,
        renderLineHighlight: "line",
        folding: false,
        glyphMargin: false,
        quickSuggestions: false,
        suggestOnTriggerCharacters: false,
        wordBasedSuggestions: "off",
        parameterHints: { enabled: false },
        inlineSuggest: { enabled: false },
        lightbulb: { enabled: monaco.editor.ShowLightbulbIconMode.Off },
        codeLens: false,
        autoClosingBrackets: "never",
        autoClosingQuotes: "never",
        autoClosingComments: "never",
        autoSurround: "never",
        autoIndent: "keep",
        formatOnPaste: false,
        formatOnType: false,
        matchBrackets: "never",
        bracketPairColorization: { enabled: false },
        guides: { bracketPairs: false, indentation: true },
        occurrencesHighlight: "off",
        selectionHighlight: false,
        contextmenu: false,
        renderValidationDecorations: "on",
        stickyScroll: { enabled: false },
      }}
    />
  );
}
