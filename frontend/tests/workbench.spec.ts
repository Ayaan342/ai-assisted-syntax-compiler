import { test, expect, type Page } from "@playwright/test";
import { examples } from "../src/constants/examples";

async function enterExample(page: Page, name: keyof typeof examples) {
  await page.locator(".source-editor .view-lines").click();
  await page.keyboard.press("Control+A");
  await page.keyboard.insertText(examples[name]);
  await expect(page.getByRole("status")).toContainText("Source changed");
}

test("lowercase a remains normal Monaco input and never runs Analyze", async ({
  page,
}) => {
  let analyzeRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/analyze") analyzeRequests += 1;
  });

  await page.goto("/");
  await page.locator(".source-editor .view-lines").click();
  await page.keyboard.press("Control+A");
  await page.keyboard.press("a");

  await expect(page.locator(".source-editor .view-lines")).toHaveText("a");
  await expect(page.getByRole("status")).toContainText("Source changed");
  expect(analyzeRequests).toBe(0);
});

test("real backend analysis, Monaco markers, and all data inspectors", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByText("Backend connected", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".source-editor .monaco-editor")).toBeVisible();
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("All checks passed");
  await page.getByRole("tab", { name: "Tokens" }).click();
  await expect(
    page.getByRole("cell", { name: "INTEGER_LITERAL", exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("tab", { name: "AST", exact: true }).click();
  await expect(
    page.locator("summary").filter({ hasText: "Program" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Symbol Table" }).click();
  await expect(
    page.getByRole("cell", { name: "main", exact: true }),
  ).toBeVisible();
  await enterExample(page, "Broken If");
  // Invalid source has no squiggles before a backend response.
  await expect(page.locator(".source-editor .squiggly-error")).toHaveCount(0);
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Diagnostics available");
  await expect(
    page.locator(".source-editor .squiggly-error").first(),
  ).toBeVisible();
  // Monaco paints marker decorations beneath its text layer, so a real pointer
  // event must bypass Playwright's interception guard at the same coordinates.
  await page
    .locator(".source-editor .squiggly-error")
    .first()
    .hover({ force: true });
  await expect(page.locator(".monaco-hover:not(.hidden)")).toContainText(
    "Mini-C backend",
  );
  await expect(page.locator(".diagnostic-row").first()).toContainText(
    "UNEXPECTED_TOKEN",
  );
  await page.locator(".diagnostic-row").first().click();
  await page.screenshot({
    path: "test-results/workbench-diagnostic.png",
    fullPage: true,
  });
});

test("real ML correction is reviewed before explicitly applying", async ({
  page,
}) => {
  await page.goto("/");
  await enterExample(page, "Broken If");
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Apply Corrected Code" }),
  ).toBeEnabled();
  await expect(page.getByRole("status")).toContainText(
    "Source has not changed",
  );
  await expect(page.locator(".history")).toContainText("INSERT_RPAREN");
  await expect(page.locator(".history")).toContainText("Groq not used");
  await expect(
    page.locator(".source-editor .squiggly-error").first(),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/workbench-correction.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Apply Corrected Code" }).click();
  await expect(page.getByRole("status")).toContainText("All checks passed");
  await expect(page.locator(".source-editor .squiggly-error")).toHaveCount(0);
});

test("Groq ambiguity-selection metadata is visible in correction review", async ({
  page,
}) => {
  const original = examples.Valid;
  const corrected = `${original}\n`;
  const location = { line: 1, column: 1, offset: 0 };
  const span = { start: location, end: location };
  const candidate = {
    id: "SYN-0001-C02",
    action: "DELETE",
    token_type: "LBRACE",
    token_lexeme: "{",
    offset: 0,
    span,
    text: "",
    reason: "Delete the trailing opener",
    grammar_context: "expression",
    diagnostic_id: "SYN-0001",
    origin: "traditional_recovery",
    parser_validated: true,
    score: 0.01,
  };
  const validation = {
    candidate,
    corrected_source: corrected,
    valid: true,
    relevant_valid: true,
    target_resolved: true,
    remaining_syntax_errors: 0,
    remaining_lexical_errors: 0,
  };
  await page.route("**/correct", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        original_code: original,
        corrected_code: corrected,
        fully_syntactically_valid: true,
        corrections_applied: 1,
        history: [
          {
            sequence: 1,
            status: "APPLIED",
            applied: true,
            diagnostic_id: "SYN-0001",
            original_error: {
              phase: "syntax",
              code: "UNEXPECTED_EOF",
              message: "Unexpected end of input",
              line: 1,
              column: 1,
              offset: 0,
              span,
            },
            prediction: {
              label: "REPLACE_BRACKET",
              confidence: 0.99,
              probabilities: { REPLACE_BRACKET: 0.99 },
            },
            selected_candidate: candidate,
            candidate_rank: 2,
            candidate_probability: 0.01,
            before_snippet: original,
            after_snippet: corrected,
            source_offset: 0,
            validation,
            reason: "ambiguity_selection_groq_parser_validated",
            llm_fallback: null,
            ambiguity_selection: {
              attempted: true,
              available: true,
              model: "mock-groq",
              selected_candidate_id: candidate.id,
              confidence: 0.91,
              reason: "Deleting the trailing opener preserves the function structure.",
              selected_candidate: candidate,
              validation,
              accepted: true,
              error: null,
            },
          },
        ],
        predictions: [],
        confidence_values: [],
        groq_fallback_used: false,
        ambiguity_selection_used: true,
        needs_llm_fallback: false,
        unresolved_syntax_diagnostics: [],
        semantic_diagnostics: [],
        stop_reason: "source_is_syntactically_valid",
      }),
    }),
  );

  await page.goto("/");
  await page.getByRole("button", { name: "Correct", exact: true }).click();

  await expect(page.locator(".history")).toContainText("Intent selector selected");
  await expect(page.locator(".history")).toContainText("91.0% selector");
  await expect(page.locator(".history")).toContainText(
    "Deleting the trailing opener preserves the function structure.",
  );
});

test("offline and missing-model errors are safe and recoverable", async ({
  page,
}) => {
  await page.route("**/health", (route) => route.abort());
  await page.goto("/");
  await expect(
    page.getByText("Backend offline", { exact: true }),
  ).toBeVisible();
  await page.route("**/correct", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"detail":"private detail"}',
    }),
  );
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  await expect(page.locator(".error-banner")).toContainText(
    "correction model is unavailable",
  );
  await expect(page.locator(".error-banner")).not.toContainText(
    "private detail",
  );
});

test("reset cancels stale analysis and clears markers", async ({ page }) => {
  await page.route("**/analyze", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.continue().catch(() => {});
  });
  await page.goto("/");
  await enterExample(page, "Broken If");
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await page.waitForTimeout(1500);
  await expect(page.getByRole("status")).toContainText(
    "Default example restored",
  );
  await expect(page.locator(".source-editor .squiggly-error")).toHaveCount(0);
});

test("narrow workspace stacks without horizontal page overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".source-editor .monaco-editor")).toBeVisible();
  const editor = await page.locator(".editor-panel").boundingBox();
  const panel = await page.locator(".analysis-panel").boundingBox();
  expect(panel!.y).toBeGreaterThan(editor!.y);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/workbench-mobile.png",
    fullPage: true,
  });
});
