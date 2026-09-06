# AI-Assisted Syntax Error Detection and Correction Compiler

This repository contains **Phases 1 through 9** of a Mini-C compiler
front-end: a PLY Lex lexer, an explicitly defined PLY Yacc grammar, source-located
AST construction and visualization, structured lexical/syntax diagnostics,
examples, tests, traditional syntax recovery, source correction candidates, and
model-independent AI context interfaces, a scoped symbol table, and basic semantic
analysis, validated synthetic ML data generation, explainable compiler-context
features, a Scikit-learn correction classifier, iterative compiler-validated
automatic correction, a constrained Groq fallback for unresolved errors, and a
FastAPI backend with a React, TypeScript, Vite, and Monaco compiler workbench.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python main.py --tokens examples\valid\demo.mc
.\.venv\Scripts\python main.py --ast examples\valid\demo.mc
.\.venv\Scripts\python main.py --tokens examples\invalid\lexical_errors.mc
.\.venv\Scripts\python main.py --errors examples\invalid\multiple_errors.mc
.\.venv\Scripts\python main.py --error-context examples\invalid\broken_if.mc
.\.venv\Scripts\python main.py --symbols examples\valid\scopes_and_functions.mc
.\.venv\Scripts\python main.py --semantic-errors examples\invalid\semantic_errors.mc
.\.venv\Scripts\python main.py --generate-dataset
.\.venv\Scripts\python main.py --train-model
.\.venv\Scripts\python main.py --predict-error examples\invalid\broken_if.mc
.\.venv\Scripts\python main.py --correct examples\invalid\broken_if.mc
.\.venv\Scripts\python main.py --suggest-corrections examples\invalid\missing_semicolon.mc
.\.venv\Scripts\python main.py --correct --auto-apply-threshold 0.30 --llm-fallback-threshold 0.20 examples\invalid\multiple_errors.mc
.\.venv\Scripts\python -m uvicorn backend.app.main:app --reload
.\.venv\Scripts\python -m pytest
```

In a second terminal, start the Phase 9 workbench:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The frontend expects the API at
`http://127.0.0.1:8000` by default. See `frontend/.env.example` to override it.

With no mode flag, the CLI defaults to token output for backward compatibility.
See `docs/mini_c_spec.md` for the language definition and `docs/grammar.md` for the
CFG and precedence table.
Recovery design and candidate semantics are documented in
`docs/error_recovery.md`.
Scope and type rules are documented in `docs/semantic_analysis.md`.
The dataset, feature, training, and prediction design is documented in
`docs/ml_correction.md`.
The Phase 6 ranking, confidence, validation, and iteration policy is documented
in `docs/automatic_correction.md`.
The optional structured Groq fallback is documented in `docs/llm_fallback.md`.
The FastAPI endpoints, schemas, error policy, and local run instructions are in
`docs/api.md`.
The Phase 9 UI architecture, compiler-logic boundary, and verification commands
are documented in `docs/frontend.md`.
