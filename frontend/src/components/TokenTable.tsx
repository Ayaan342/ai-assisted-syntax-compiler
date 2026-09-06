import type { Token } from "../types/compiler";
export function TokenTable({ tokens }: { tokens: Token[] | null }) {
  return tokens ? (
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>TYPE</th>
          <th>LEXEME</th>
          <th>LINE</th>
          <th>COLUMN</th>
        </tr>
      </thead>
      <tbody>
        {tokens.map((t, i) => (
          <tr key={i}>
            <td className="muted">{i + 1}</td>
            <td className="accent">{t.type}</td>
            <td>{t.lexeme}</td>
            <td>{t.line}</td>
            <td>{t.column}</td>
          </tr>
        ))}
      </tbody>
    </table>
  ) : (
    <div className="empty">
      Open this tab to fetch the backend token stream.
    </div>
  );
}
