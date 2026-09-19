# Design Language: Enterprise Dashboard

Use this context when restyling basic static HTML dashboards. Target exact visual
language below, not a generic "modern enterprise" approximation.

Preserve existing content, data, labels, functionality, URLs, and behavior.
Change presentation, hierarchy, spacing, color, typography, surfaces, and layout.

## Core visual identity

```text
precise
dense
functional
neutral
flat
rectilinear
high-contrast
grid-aligned
minimal
```

UI feels engineered, not decorative.

Use:
- flat rectangular surfaces
- 1px structural borders
- layered neutral backgrounds
- compact controls
- dense tables
- restrained color
- strong typographic hierarchy
- deliberate whitespace

Avoid:
- gradients
- glassmorphism
- blur
- neumorphism
- large shadows
- pill-shaped controls
- excessive corner radius
- decorative UI
- oversized headings
- arbitrary colors
- arbitrary spacing
- excessive whitespace

Default radius: `0px`. Do not round cards/controls unless source structure
specifically requires it.

## Typography

Use exact font stacks:

```css
font-family: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
```

```css
font-family: "IBM Plex Mono", "Menlo", "DejaVu Sans Mono",
  "Bitstream Vera Sans Mono", Courier, monospace;
```

Do not substitute Inter, Roboto, system-ui, Poppins, etc.

### Productive dashboard type

Use productive typography by default. Base size: `14px`.

```text
body-compact-01  14px / 18px / 400 / .16px
body-01          14px / 20px / 400 / .16px

heading-compact-01  14px / 18px / 600 / .16px
heading-01          14px / 20px / 600 / .16px

heading-03       20px / 28px / 400
heading-04       28px / 36px / 400
heading-05       32px / 40px / 400
heading-06       42px / 50px / 300
heading-07       54px / 64px / 300
```

Use expressive `16px` base typography only for genuinely editorial/marketing
regions. Basic dashboards should use productive density.

Use sentence case. Avoid decorative text coloring and all-caps UI.
Use monospace for code, identifiers, or technical numeric treatment.

## Themes

Support both light and dark modes through semantic tokens. Never hard-code
component colors independently per mode.

Four valid base themes:

```text
White   → light, background #ffffff
Gray 10 → light, background #f4f4f4
Gray 90 → dark,  background #262626
Gray 100 → dark, background #161616
```

### Light: White theme

```text
background       #ffffff
layer-01         #f4f4f4
layer-02         #ffffff
layer-03         #f4f4f4

text-primary     #161616
text-secondary   #525252
text-placeholder #8d8d8d

border-subtle    #e0e0e0
border-strong    #8d8d8d
```

### Light: Gray 10 theme

```text
background       #f4f4f4
layer-01         #ffffff
layer-02         #f4f4f4
layer-03         #ffffff

text-primary     #161616
text-secondary   #525252
text-placeholder #8d8d8d

border-subtle    #e0e0e0
border-strong    #8d8d8d
```

Light themes alternate White and Gray 10 across layers.
Avoid muddy midtones.

### Dark: Gray 100 theme

Best default for dark technical dashboards.

```text
background       #161616
layer-01         #262626
layer-02         #393939
layer-03         #525252

text-primary     #f4f4f4
text-secondary   #c6c6c6
text-placeholder #8d8d8d

border-subtle    #393939
border-strong    #6f6f6f
```

### Dark: Gray 90 theme

```text
background       #262626
layer-01         #393939
layer-02         #525252
layer-03         #6f6f6f

text-primary     #f4f4f4
text-secondary   #c6c6c6
text-placeholder #8d8d8d

border-subtle    #525252
border-strong    #8d8d8d
```

Dark layers become progressively lighter as depth increases.
Never place a normal component surface darker than its parent.

### Shared interaction colors

```text
blue-60          #0f62fe   primary interactive
blue-70          #0043ce   hover / stronger interaction
blue-40          #78a9ff   dark-theme-friendly blue

red-60           #da1e28   error
green-60         #24a148   success
yellow-30        #f1c21b   warning
blue-60          #0f62fe   info
```

Use semantic roles:

```text
background
layer
field
text-primary
text-secondary
icon-primary
border-subtle
border-strong
link-primary
interactive
support-error
support-success
support-warning
support-info
focus
```

Accent is for links, primary actions, active/selected UI, and meaningful
emphasis. Status must remain understandable without color alone.

## Grid and spacing

Use responsive **16-column 2x grid** as mental model.

Use spacing based on multiples of `2`, `4`, and `8`.

```text
2   micro
4   tight
8   related elements
12  compact group
16  standard inset
24  component separation
32  section separation
48  major separation
64+ page-level separation
```

Avoid arbitrary values such as `13px`, `19px`, `27px`.

For dense dashboards favor `8px`, `12px`, and `16px` spacing.

## Page structure

Typical dashboard:

```text
full-width header / shell
↓
page title + metadata
↓
summary metrics
↓
primary table/chart/data
↓
secondary analysis
↓
supporting content
```

Align major regions to shared grid boundaries.

Do not force every region into a card.

## Surfaces

Use layer hierarchy:

```text
background → page
layer-01    → primary container
layer-02    → nested container
layer-03    → deeper/floating surface
```

Use borders for structural boundaries.
Avoid shadows on ordinary dashboard content.
Reserve elevation for menus, popovers, dialogs, and other floating UI.

## Metric cards

Compact and information-first:

```text
small label
prominent value
optional supporting detail
```

Keep metric cards consistent in height, padding, alignment, and border treatment.
Do not make every metric a visually heavy floating card.

## Tables

Use dense, readable tables:

```text
14px productive body
14px semibold headers
compact row height
consistent cell padding
subtle separators
aligned numeric values
clear header distinction
responsive horizontal overflow when needed
```

Keep table width aligned to page grid.
Use semantic color only for meaningful state/performance.

Progress bars: compact rectangular track/fill + numeric value.

## Controls

Rectangular, compact, consistent.

```text
24px  extra-small
32px  small
40px  medium
48px  large
```

Dashboard controls usually use `32px` or `40px`.

Buttons:
- sentence case
- 14px productive text
- regular weight
- compact geometry
- blue primary
- neutral secondary
- text/outline tertiary
- red destructive
- aligned icons
- no pill shape

## Header / shell

Application header:

```text
height: 48px
full viewport width
14px text
600 weight product/page identity
400 weight navigation/actions
48px interactive hit areas
16px horizontal padding
subtle bottom boundary
```

Keep shell functional and visually quiet.

## States

Interactive elements need appropriate:

```text
default
hover
focus
active
selected
disabled
```

Focus must remain clearly visible. Do not remove outlines without an equivalent
accessible focus treatment.

## Accessibility

Preserve:
- semantic HTML
- logical heading hierarchy
- keyboard operation
- visible focus
- associated labels
- meaningful alt text
- adequate contrast
- non-color status cues
- responsive usability

Prefer native HTML controls over div-based widgets.

## Responsive behavior

Desktop:
- use 16-column layout
- group metrics horizontally
- maximize useful information density

Tablet:
- reduce column spans
- wrap metric groups
- preserve table readability

Mobile:
- stack major regions
- collapse navigation where needed
- allow tables to scroll horizontally
- keep controls usable
- reduce padding before reducing text legibility

Never create page-level horizontal overflow.

## Conversion

```text
inspect
→ preserve content/functionality
→ load/use IBM Plex
→ establish productive 14px baseline
→ choose White/G10 or G90/G100 theme
→ apply semantic color tokens
→ apply correct layer hierarchy
→ align to 16-column grid
→ normalize 2/4/8 spacing
→ flatten excessive cards/shadows/radii
→ normalize metrics/tables/controls
→ add states/focus
→ make responsive
→ remove obsolete CSS
```

Do not redesign information architecture unless broken.
Do not invent components content does not require.

## Fidelity test

A faithful result should visibly exhibit:

```text
IBM Plex Sans
14px productive density
0px geometry
16-column grid
2/4/8 spacing rhythm
semantic theme tokens
correct light/dark layer progression
neutral gray dominance
core blue #0f62fe
1px borders
compact controls
minimal shadows
sentence case
dense data presentation
```

Blue + gray + cards alone is insufficient.

## Output

When source HTML is provided, return complete transformed HTML/CSS/JS.

Keep implementation self-contained unless existing architecture requires otherwise.
Preserve existing JavaScript behavior and data.
Do not explain design decisions unless asked.
