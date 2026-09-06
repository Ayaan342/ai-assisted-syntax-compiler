import type { Scope, SymbolTable } from "../types/compiler";
function ScopeView({ scope }: { scope: Scope }) {
  return (
    <details open className="scope">
      <summary>
        {scope.name} <code>{scope.kind}</code>
      </summary>
      {scope.symbols.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>NAME</th>
              <th>TYPE</th>
              <th>KIND</th>
              <th>LOCATION</th>
            </tr>
          </thead>
          <tbody>
            {scope.symbols.map((s) => (
              <tr key={s.id}>
                <td className="accent">{s.name}</td>
                <td>{s.type.display}</td>
                <td>{s.kind}</td>
                <td>
                  Ln {s.line}:{s.column}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {scope.children.map((child) => (
        <ScopeView key={child.id} scope={child} />
      ))}
    </details>
  );
}
export function SymbolTableView({ symbols }: { symbols: SymbolTable | null }) {
  return symbols ? (
    <div className="tree">
      <ScopeView scope={symbols.root} />
    </div>
  ) : (
    <div className="empty">
      Symbol table unavailable. Semantic analysis runs after valid syntax.
    </div>
  );
}
