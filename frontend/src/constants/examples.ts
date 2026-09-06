const valid = `int main() {
    int x = 10;

    if (x > 5) {
        return x;
    }

    return 0;
}`;
export const examples: Record<string, string> = {
  Valid: valid,
  "Missing Semicolon": valid.replace("10;", "10"),
  "Broken If": valid.replace("(x > 5)", "(x > 5"),
  "Misspelled Return": valid.replace("return x", "retrun x"),
};
export const DEFAULT_CODE = valid;
