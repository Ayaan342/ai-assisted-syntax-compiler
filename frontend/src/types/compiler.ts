export interface SourceLocation {
  line: number;
  column: number;
  offset: number;
}
export interface SourceSpan {
  start: SourceLocation;
  end: SourceLocation;
}
export type Phase = "lexical" | "syntax" | "semantic";
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };
export interface Candidate {
  id: string;
  action: "INSERT" | "DELETE" | "REPLACE";
  token_type: string | null;
  token_lexeme: string | null;
  offset: number;
  span: SourceSpan;
  text: string;
  reason: string;
  grammar_context: string;
  diagnostic_id: string;
  origin: string;
  parser_validated: boolean | null;
  score: number | null;
}
export interface Diagnostic {
  phase: Phase;
  code: string;
  message: string;
  line: number;
  column: number;
  offset: number;
  span: SourceSpan;
  severity?: string;
  diagnostic_id?: string;
  unexpected_token?: string | null;
  unexpected_lexeme?: string | null;
  expected_tokens?: string[];
  grammar_context?: string | null;
  correction_candidates?: Candidate[];
}
export interface Token {
  type: string;
  lexeme: string;
  value: JsonValue;
  line: number;
  column: number;
  offset: number;
  span: SourceSpan;
}
export interface AstNode {
  node: string;
  span: SourceSpan;
  [key: string]: unknown;
}
export interface SymbolType {
  kind: string;
  base: string;
  display: string;
  parameter_types: SymbolType[];
}
export interface Symbol {
  id: string;
  name: string;
  kind: string;
  type: SymbolType;
  scope_id: string;
  line: number;
  column: number;
  offset: number;
  span: SourceSpan;
  array_size: number | null;
}
export interface Scope {
  id: string;
  name: string;
  kind: string;
  parent_id: string | null;
  symbols: Symbol[];
  children: Scope[];
}
export interface SymbolTable {
  root: Scope;
}
export interface Prediction {
  label: string;
  confidence: number;
  probabilities: Record<string, number>;
}
export interface Validation {
  candidate: Candidate;
  corrected_source: string;
  valid: boolean;
  relevant_valid: boolean;
  target_resolved: boolean;
  remaining_syntax_errors: number;
  remaining_lexical_errors: number;
}
export interface GroqFallback {
  attempted: boolean;
  available: boolean;
  model: string;
  accepted: boolean;
  error: string | null;
  suggestion: {
    action: Candidate["action"];
    replacement_text: string;
    target_start: number;
    target_end: number;
    reason: string;
  } | null;
  validation: Validation | null;
}
export interface CorrectionHistory {
  sequence: number;
  status: "APPLIED" | "SUGGESTED" | "UNRESOLVED";
  applied: boolean;
  diagnostic_id: string;
  original_error: Diagnostic;
  prediction: Prediction;
  selected_candidate: Candidate | null;
  candidate_rank: number | null;
  candidate_probability: number | null;
  before_snippet: string;
  after_snippet: string | null;
  source_offset: number;
  validation: Validation | null;
  reason: string | null;
  llm_fallback: GroqFallback | null;
}
export interface AnalysisResponse {
  success: boolean;
  token_count: number;
  lexical: { success: boolean; errors: Diagnostic[] };
  syntax: { success: boolean; errors: Diagnostic[] };
  semantic: { ran: boolean; success: boolean | null; errors: Diagnostic[] };
  ast: AstNode | null;
  symbols: SymbolTable | null;
}
export interface CorrectionResponse {
  success: boolean;
  original_code: string;
  corrected_code: string;
  fully_syntactically_valid: boolean;
  corrections_applied: number;
  history: CorrectionHistory[];
  predictions: Prediction[];
  confidence_values: number[];
  groq_fallback_used: boolean;
  needs_llm_fallback: boolean;
  unresolved_syntax_diagnostics: Diagnostic[];
  semantic_diagnostics: Diagnostic[];
  stop_reason: string;
}
export interface TokensResponse {
  success: boolean;
  token_count: number;
  tokens: Token[];
  lexical_errors: Diagnostic[];
}
export interface AstResponse {
  success: boolean;
  ast: AstNode | null;
  lexical_errors: Diagnostic[];
  syntax_errors: Diagnostic[];
}
export interface SymbolsResponse {
  success: boolean;
  ran: boolean;
  symbols: SymbolTable | null;
  lexical_errors: Diagnostic[];
  syntax_errors: Diagnostic[];
  semantic_errors: Diagnostic[];
}
export interface Health {
  status: string;
  ml_model_loaded: boolean;
  groq_configured: boolean;
}
