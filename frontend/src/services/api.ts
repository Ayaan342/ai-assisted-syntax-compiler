import type {
  AnalysisResponse,
  AstResponse,
  CorrectionResponse,
  Health,
  SymbolsResponse,
  TokensResponse,
} from "../types/compiler";
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/$/, "");
export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
  ) {
    super(message);
  }
}
async function request<T>(
  path: string,
  code?: string,
  signal?: AbortSignal,
): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: code === undefined ? "GET" : "POST",
      headers:
        code === undefined ? undefined : { "Content-Type": "application/json" },
      body: code === undefined ? undefined : JSON.stringify({ code }),
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(90000)])
        : AbortSignal.timeout(90000),
    });
    if (!response.ok) {
      const message =
        response.status === 503
          ? "The correction model is unavailable. Train the backend model, then try again."
          : response.status === 422
            ? "The backend could not accept this source. Use at most 100,000 characters."
            : "The backend could not complete this request. Please try again.";
      throw new ApiError(message, response.status);
    }
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError || signal?.aborted) throw error;
    throw new ApiError(
      "Could not reach the compiler. Check that the backend is running, then retry.",
    );
  }
}
export const checkHealth = (signal?: AbortSignal) =>
  request<Health>("/health", undefined, signal);
export const analyzeCode = (code: string, signal?: AbortSignal) =>
  request<AnalysisResponse>("/analyze", code, signal);
export const correctCode = (code: string, signal?: AbortSignal) =>
  request<CorrectionResponse>("/correct", code, signal);
export const getTokens = (code: string, signal?: AbortSignal) =>
  request<TokensResponse>("/tokens", code, signal);
export const getAst = (code: string, signal?: AbortSignal) =>
  request<AstResponse>("/ast", code, signal);
export const getSymbols = (code: string, signal?: AbortSignal) =>
  request<SymbolsResponse>("/symbols", code, signal);
