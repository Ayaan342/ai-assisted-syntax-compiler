import type { AstNode } from "../types/compiler";
function Branch({ name, value }: { name: string; value: unknown }) {
  if (name === "span" || value === null) return null;
  if (typeof value !== "object")
    return (
      <div className="tree-value">
        <span>{name}</span>
        <code>{String(value)}</code>
      </div>
    );
  const entries = Array.isArray(value)
    ? value.map((item, i) => [String(i), item] as const)
    : Object.entries(value);
  const nodeName =
    !Array.isArray(value) && "node" in value ? String(value.node) : name;
  return (
    <details
      open={name === "root" || name === "functions"}
      className="tree-branch"
    >
      <summary>
        {nodeName}{" "}
        <span>
          {Array.isArray(value)
            ? `${value.length} items`
            : name === "root"
              ? "AST"
              : name}
        </span>
      </summary>
      <div>
        {entries
          .filter(([key]) => key !== "node")
          .map(([key, item]) => (
            <Branch key={key} name={key} value={item} />
          ))}
      </div>
    </details>
  );
}
export function ASTView({ ast }: { ast: AstNode | null }) {
  return ast ? (
    <div className="tree">
      <Branch name="root" value={ast} />
    </div>
  ) : (
    <div className="empty">
      AST unavailable. Analyze syntactically valid source to build the tree.
    </div>
  );
}
