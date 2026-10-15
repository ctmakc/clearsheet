# Clearsheet design decision (locked 2026-10-15)

Subject world: a nurse's desk at discharge. The discharge summary printout, a yellow
highlighter, the medication administration record (MAR) grid, the pill organizer the
patient takes home.

Directions considered:
1. HIGHLIGHTER TRACE (chosen). Chart paper, Lexend + Noto Sans, highlighter swipes behind
   every source quote, MAR-style ruled rows.
2. DOSETTE. Navy pill-box plastic, translucent lids by time of day. Rejected for the console
   (too playful for a clinical review tool); its grid survives inside the patient sheet.
3. WRISTBAND. Hospital ID band strip as the frame. Rejected: decoration with no job.

Tokens
- paper `#F6F7F4` (cool chart paper), panel `#FFFFFF`, rule `#D5D9D3`, ink `#18222F`, ink-2 `#4A5563`
- highlighter `#EDF25C` (only as a swipe behind source text, never on buttons)
- states (semantic only): ok `#2E7D4F`, review `#A86312`, blocked `#B42318`
- action ink `#1D3F8F` (buttons, focus ring)
- Fonts: Lexend 500/600 (headings, numbers; designed for reading proficiency),
  Noto Sans + Noto Sans SC / Arabic / Gurmukhi (all patient text), JetBrains Mono for ids/quotes
- One radius: 4px. Borders, no shadows except the printed sheet preview.

Signature: the trace. Left pane is the masked discharge summary; every extracted line on the
right carries an id tag; hovering or selecting a line draws a highlighter swipe across its
source quote on the left.

Motion: highlighter swipe draws left to right (background-size 0 to 100%, 380ms, expo-out);
state chip stamps on change (scale 1.15 to 1, 160ms); rows enter with a 40ms stagger once per
run. prefers-reduced-motion: swipes appear without drawing, no stagger.

Patient sheet: Letter/A4 printable. Patient language first, English under it in smaller type.
Medicines as a dosette grid (morning / midday / evening / bedtime / only when needed).
Emergency block in blocked-red, verbatim from the source plus translation.
