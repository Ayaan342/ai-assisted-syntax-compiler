import {
  ListBullets,
  TreeStructure,
  Table,
  Wrench,
  WarningCircle,
} from "@phosphor-icons/react";
export const tabs = [
  "Tokens",
  "AST",
  "Symbol Table",
  "Corrections",
  "Diagnostics",
] as const;
export type Tab = (typeof tabs)[number];
const icons = [ListBullets, TreeStructure, Table, Wrench, WarningCircle];
export function InspectorTabs({
  active,
  onChange,
  count,
}: {
  active: Tab;
  onChange: (tab: Tab) => void;
  count: number;
}) {
  return (
    <div
      className="inspector-tabs"
      role="tablist"
      aria-label="Compiler inspector"
    >
      {tabs.map((tab, i) => {
        const Icon = icons[i];
        return (
          <button
            id={`tab-${i}`}
            aria-controls="inspector-content"
            role="tab"
            aria-selected={active === tab}
            tabIndex={active === tab ? 0 : -1}
            key={tab}
            onClick={() => onChange(tab)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (i + 1) % tabs.length
                  : event.key === "ArrowLeft"
                    ? (i + tabs.length - 1) % tabs.length
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? tabs.length - 1
                        : -1;
              if (next >= 0) {
                event.preventDefault();
                onChange(tabs[next]);
                document.getElementById(`tab-${next}`)?.focus();
              }
            }}
          >
            <Icon size={16} />
            {tab}
            {tab === "Diagnostics" && <span className="count">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}
