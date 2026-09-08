import { useEffect, useRef } from "react";
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
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const index = tabs.indexOf(active);
    refs.current[index]?.scrollIntoView({
      behavior: "auto",
      block: "nearest",
      inline: "nearest",
    });
  }, [active]);

  return (
    <div className="inspector-tabs-wrap">
      <div
        className="inspector-tabs"
        role="tablist"
        aria-label="Compiler inspector"
      >
        {tabs.map((tab, index) => {
          const Icon = icons[index];
          return (
            <button
              ref={(element) => {
                refs.current[index] = element;
              }}
              id={`tab-${index}`}
              aria-controls="inspector-content"
              role="tab"
              aria-selected={active === tab}
              tabIndex={active === tab ? 0 : -1}
              key={tab}
              onClick={() => onChange(tab)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % tabs.length
                    : event.key === "ArrowLeft"
                      ? (index + tabs.length - 1) % tabs.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? tabs.length - 1
                          : -1;
                if (next >= 0) {
                  event.preventDefault();
                  onChange(tabs[next]);
                  refs.current[next]?.focus();
                }
              }}
            >
              <Icon size={16} />
              {tab}
              {tab === "Diagnostics" && (
                <span className="count">{count}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
