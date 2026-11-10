# Accessibility checklist (WCAG 2.2 AA)

- **Scope:** every page of the web app: sign-in and request access, welcome, runs, new brief,
  run (plan, report, evidence, timeline), documents, usage, activity, workspace settings,
  access administration, not-found.
- **Automated** rows are verified on every CI run by `frontend/e2e/a11y.spec.ts` (axe-core
  4.14 with the WCAG 2.0/2.1/2.2 A and AA rule sets, in light and dark mode, plus a 360 px
  layout check and a keyboard test) and by the Vitest suites.
- **Manual** rows need a person with assistive technology. Status (2026-11-06): **blocked by
  owner**, not yet done. Automated tools catch only part of WCAG; passing them is not a
  conformance claim.

## Automated

| Criterion | What is checked | Evidence | Status |
| --- | --- | --- | --- |
| 1.1.1 Non-text content | Images and icons have text alternatives or are hidden from assistive technology | axe (`image-alt`, `svg-img-alt`), decorative marks `aria-hidden` | Pass |
| 1.3.1 Info and relationships | Labels tied to inputs; tables have headers and captions; lists are lists; landmarks (`banner`, `nav`, `main`) | axe (`label`, `th-has-data-cells`, `list`), Vitest role queries | Pass |
| 1.4.3 Contrast (minimum) | Text contrast at least 4.5:1, large text 3:1, in light **and dark** mode | axe `color-contrast` on every page in both schemes | Pass |
| 1.4.10 Reflow | No horizontal scrolling at 360 CSS px (equivalent to 1280 px at 400% zoom for most layouts); data tables keep essential columns | `a11y.spec.ts` "fits a 360 px wide screen" | Pass |
| 1.4.11 Non-text contrast | Focus rings and input borders visible | Design tokens (`--focus`, `--border-strong`); visual review in screenshots | Pass (manual visual check recommended) |
| 2.1.1 Keyboard | Every action reachable and operable by keyboard; confirmations operable | Keyboard test (skip link, settings, confirm, Escape); Playwright drives journeys by role | Pass |
| 2.4.1 Bypass blocks | Skip link is the first focusable element and moves focus to `main` | `AppShell.test.tsx`, keyboard E2E | Pass |
| 2.4.2 Page titled | Every page sets a specific title | Vitest `document.title` checks, `useDocumentTitle` on every page | Pass |
| 2.4.3 Focus order / 2.4.7 Focus visible | Focus moves into confirmations and back; visible outline | `ui.test.tsx` (ConfirmButton), `:focus-visible` style | Pass |
| 2.4.11 Focus not obscured (2.2) | Sticky top bar and notifications do not hide the focused element | Notifications sit bottom-right with `pointer-events` only on themselves | Pass (manual check recommended at 200% zoom) |
| 2.5.3 Label in name | Visible text is part of the accessible name (e.g. "Access, 2 pending requests") | Vitest and E2E query by visible names | Pass |
| 2.5.8 Target size (2.2) | Interactive targets at least 24x24 px | axe `target-size` (wcag22aa) | Pass |
| 3.3.1 Error identification / 3.3.3 Suggestion | Errors say what happened and what to do (sign-in codes, 403 "Not permitted", 409 last admin, 429 wait) | `SignInPage.test.tsx`, `ui.test.tsx`, `WorkspaceSettingsPage.test.tsx` | Pass |
| 4.1.2 Name, role, value | Controls expose names and states (`aria-expanded`, `aria-pressed`, `aria-current`) | axe `aria-*` rules, Vitest role queries | Pass |
| 4.1.3 Status messages | Notifications and status banners are announced without moving focus | Polite/assertive live regions (`toast.tsx`), `role="status"`/`"alert"` banners | Pass (screen-reader confirmation pending, below) |
| 2.3.3 / reduced motion | Animations off with *reduce motion* | CSS `prefers-reduced-motion` | Pass |

## Manual (blocked by owner)

| Check | How | Result | Date, tester |
| --- | --- | --- | --- |
| NVDA + Firefox or Chrome on Windows | Complete usability tasks 1-6 ([usability-study.md](usability-study.md)) by screen reader only; note anything not announced or ambiguous | | |
| VoiceOver + Safari on iOS | Sign in, open a run, open a citation | | |
| 200% and 400% browser zoom | Every page usable, nothing clipped, no sideways scrolling except data tables | | |
| Windows high contrast / forced colours | Focus, badges and buttons stay visible | | |
| Keyboard only, full workflow | Brief to export without a mouse, with focus always visible | | |
| Cognitive load review | Plain-language labels and error messages read by someone outside the project | | |

Record every problem as an issue with the WCAG criterion, the page, and steps to reproduce.
