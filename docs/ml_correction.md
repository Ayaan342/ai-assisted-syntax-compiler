# Phase 5 Explainable ML Correction Classifier

## Role of ML

The compiler remains authoritative. PLY Lex/Yacc detects the syntax problem, the
recovery layer reports parser expectations and generates structural candidates, and
only then does the classifier predict the most likely correction class.

```text
Compiler detects the problem.
ML predicts the most likely intended correction.
The compiler will later validate and apply a selected correction.
```

Phase 5 does not automatically select or apply edits and does not use an LLM.

## Correction classes

- `INSERT_SEMICOLON`
- `INSERT_RPAREN`
- `INSERT_LPAREN`
- `INSERT_RBRACKET`
- `INSERT_RBRACE`
- `DELETE_EXTRA_TOKEN`
- `REPLACE_BRACKET`
- `REPLACE_OPERATOR`
- `CORRECT_KEYWORD`

The enum and dataset format are extensible without changing the compiler lexer or
parser.

## Synthetic dataset

`SyntheticDatasetGenerator` creates one controlled mutation in each otherwise valid
Mini-C program. It varies identifiers, numeric literals, indexes, and keyword
misspellings while cycling through correction classes in balanced quotas.

A sample is retained only when:

1. the original source parses successfully;
2. the corrupted source creates a real syntax diagnostic;
3. the compiler produces an `ErrorContext`;
4. the ground-truth edit corresponds to a compiler correction candidate;
5. applying that edit and re-parsing restores syntactic validity.

Each JSONL record stores original/corrupted source, label, injection location,
parser diagnostic, full error context, compiler candidates, and the validated
ground-truth candidate. The default dataset contains 1,008 records: 112 for each of
the nine classes.

## Explainable features

The model receives flat compiler-derived features rather than raw programs:

- unexpected/current token type and lexeme;
- previous two and following two token types;
- previous lexeme and a compact nearby token pattern;
- grammar context and enclosing construct;
- sorted expected-token signature;
- candidate action and token signatures;
- parenthesis, brace, and bracket depths;
- explicit expected-token flags for `;`, `(`, `)`, `]`, and `}`;
- presence of insertion, deletion, and replacement candidates;
- nearest Mini-C keyword, its source position, edit distance, normalized distance,
  and a close-match flag.

Keyword similarity is computed after deterministic lexing. Misspelled identifiers
such as `retrun` remain identifiers; neither the lexer nor the feature extractor
silently changes source.

## Model and preprocessing

The saved Scikit-learn `Pipeline` contains:

1. `DictVectorizer`, which one-hot encodes categorical feature/value pairs and keeps
   numeric compiler features numeric;
2. balanced multinomial-capable `LogisticRegression` with a fixed random seed.

Logistic regression was selected because it is small, deterministic, supports
`predict_proba`, and is straightforward to explain in a compiler-design viva.

Training uses a reproducible stratified 80/20 split (`random_state=42`). Evaluation
returns accuracy, a per-class precision/recall/F1 report, and a confusion matrix.
Confidence is the real probability reported by `predict_proba`; it is never invented.

The reference 1,008-record run used 806 training and 202 held-out records and scored
1.000 accuracy with 1.000 precision, recall, and F1 for every class. This high score
is expected for controlled single-error templates and should not be interpreted as
performance on arbitrary real-world C mistakes.

## Persistence and prediction

The fitted pipeline is stored with joblib at
`models/syntax_error_classifier.joblib`. Loading restores both vectorization and the
classifier, preventing training/prediction feature drift.

`MLCorrectionPredictor.predict(context)` returns the predicted class, its confidence,
and probabilities for every trained class.

## Candidate-ranking boundary

`candidate_ranker.py` maps compiler candidates to compatible correction classes and
can attach the corresponding model probability. It does not apply an edit or decide
that the top candidate is safe. Phase 6 can combine this compatibility value with
parser validation and selection policy.

## Commands

```powershell
py main.py --generate-dataset
py main.py --train-model
py main.py --predict-error examples\invalid\broken_if.mc
```

Paths and generation size can be overridden using `--dataset-path`, `--model-path`,
and `--dataset-size`.
