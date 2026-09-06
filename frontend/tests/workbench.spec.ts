import { test, expect } from "@playwright/test";

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
  await page.getByLabel("Source example").selectOption("Broken If");
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
  await page.getByLabel("Source example").selectOption("Broken If");
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
  await page.getByLabel("Source example").selectOption("Broken If");
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
