# Mini-C Workbench Design Direction

The interface uses a graphite workspace, quiet mint accents, Geist for interface
copy, and Geist Mono for source and compiler data. The visual hierarchy is shaped
like a desktop compiler tool: compact command bar, dominant source editor,
persistent analysis rail, and a full-width data inspector.

The `gpt-taste` guidance is applied to typography, spacing rhythm, control
contrast, restraint, and responsive composition. Marketing-page conventions such
as a hero, AIDA sections, stock imagery, large scroll chapters, and GSAP effects
are intentionally excluded because they conflict with a dense, stable IDE. Motion
is limited to short control-state transitions and respects reduced-motion user
preferences.

The 70/30 editor-to-analysis split remains the core composition. At narrow widths,
the two regions stack and the inspector tabs scroll horizontally without causing
page overflow. Diagnostic amber is reserved for compiler failures; mint indicates
successful backend states and the primary correction action.
