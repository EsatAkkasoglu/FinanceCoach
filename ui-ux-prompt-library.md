# The UI/UX AI Prompt Library

A systematic toolkit of AI prompts for auditing and improving any website's design and user experience — built with Three.js and modern motion design woven throughout.

**How to use this:** Every prompt is a template. Replace `{placeholders}` with your specifics, then paste into your AI assistant of choice. For best results, give the AI something concrete to look at — a screenshot, a live URL, a Figma link, or pasted component code. AI design feedback is far sharper when grounded in an actual artifact than when reasoning in the abstract.

**Pro tips that apply to every prompt below:**

- **Always provide an artifact.** "Critique my landing page" → vague. "Critique this screenshot / this URL / this JSX" → specific and actionable.
- **Give the AI a role.** Prefixing with *"You are a senior product designer who has shipped consumer apps used by millions"* meaningfully raises the quality of the output.
- **Ask for prioritization, not just a list.** Add *"Rank findings by impact-to-effort ratio and tell me the single highest-leverage change."*
- **Constrain the output format.** Ask for a table, a numbered list with severity ratings, or a diff. Unstructured walls of text are hard to act on.
- **Iterate.** The first response is a draft. Follow up with *"Now go deeper on #2"* or *"Show me three concrete variations of that."*

---

## Table of Contents

1. [Part 1 — UI/UX Audit Prompts](#part-1--uiux-audit-prompts)
2. [Part 2 — UI Improvement Prompts](#part-2--ui-improvement-prompts)
3. [Part 3 — UX Enhancement Prompts](#part-3--ux-enhancement-prompts)
4. [Part 4 — Design Variations & A/B Testing Prompts](#part-4--design-variations--ab-testing-prompts)
5. [Part 5 — Style Guides & Design Systems Prompts](#part-5--style-guides--design-systems-prompts)
6. [Part 6 — Three.js & Modern Animation Prompts](#part-6--threejs--modern-animation-prompts)
7. [Tailored Section — Prompts for Your Stack](#tailored-section--prompts-for-your-stack)
8. [Appendix — Reusable Variables & Workflow Recipes](#appendix--reusable-variables--workflow-recipes)

---

## Part 1 — UI/UX Audit Prompts

Use these to get an honest, structured read on where your site stands today. Run them one category at a time rather than asking for "a full audit" in one shot — you'll get deeper analysis per dimension.

### 1.1 Master audit (start here)

```
You are a senior product designer conducting a heuristic evaluation.
I'll give you {a screenshot / a live URL / the page's HTML+CSS}.

Audit this screen across these dimensions and rate each 1–5 with a one-line
justification:
- Visual hierarchy (does the eye land on what matters first?)
- Color & contrast
- Typography & readability
- Navigation clarity
- Spacing & layout rhythm
- Mobile responsiveness (if visible)
- Accessibility (obvious issues only)
- Overall first impression / "what is this and what do I do here?"

Then give me: the 3 most damaging problems, and the single change with the
highest impact-to-effort ratio. Be specific and blunt — I want to fix real
issues, not hear that it "looks clean."

Artifact: {paste / attach}
```

### 1.2 Visual hierarchy

```
Analyze the visual hierarchy of this screen. Map the intended reading order
(where should the eye go 1st, 2nd, 3rd?) versus the actual reading order your
eye follows. Where do they diverge?

Evaluate: size contrast, weight contrast, color/emphasis, positioning, and
whitespace as hierarchy tools. Tell me which element is fighting for attention
that shouldn't be, and which primary action is under-emphasized.

Give me 3 specific adjustments (e.g. "increase the H1 from 32px to 44px and
drop the subtitle to a muted gray") to make the hierarchy unmistakable.

Artifact: {screenshot / URL}
```

### 1.3 Color scheme consistency

```
Audit the color usage on {URL / these screenshots}. Extract the apparent
palette (primary, secondary, accent, neutrals, semantic colors for
success/warning/error). Identify:
- Inconsistencies (near-duplicate grays, off-brand one-offs, colors used for
  no systematic reason)
- Whether the accent/CTA color is reserved for actions or diluted by overuse
- Contrast failures against WCAG AA (4.5:1 body text, 3:1 large text/UI)
- Whether the palette supports a clear light/dark mode

Output a cleaned-up token set (hex values + semantic names) and a short list of
"replace X with Y" fixes.
```

### 1.4 Typography & readability

```
Evaluate the typography of {URL / screenshot}. Assess:
- Type scale: how many distinct sizes/weights are in use, and is it a coherent
  scale or ad hoc?
- Line length (target 50–75 characters for body)
- Line height / leading
- Font pairing and whether the typefaces suit the product's tone
- Readability issues: low contrast, all-caps overuse, tracking problems,
  text-over-image legibility

Propose a clean type scale (e.g. a modular scale with named roles: display,
h1–h4, body, caption) with specific px/rem values, weights, and line-heights.
```

### 1.5 Navigation intuitiveness

```
You are running a first-click usability heuristic. Looking at {URL /
screenshot of the nav}, evaluate:
- Is it obvious where the user is and where they can go?
- Are nav labels written in the user's language or internal jargon?
- Is the information scent strong (can users predict what's behind each link)?
- How many top-level items are there — is it within the 5±2 comfortable range?
- Mobile: is the nav pattern (hamburger / tab bar / etc.) appropriate?

Run this scenario through it: "{a real task, e.g. 'a new user wants to find
pricing'}". Trace the path. Where would they hesitate or guess wrong? Suggest a
clearer structure and labels.
```

### 1.6 Mobile responsiveness

```
Review this layout for mobile (~375px wide) and tablet (~768px).
{Provide: mobile screenshot, OR desktop screenshot + "infer the likely mobile
issues", OR the responsive CSS.}

Flag: tap targets under 44×44px, text that will wrap awkwardly or truncate,
horizontal scroll risks, images/sections that won't reflow well, sticky
elements that eat the viewport, and any hover-only interactions that break on
touch. Prioritize the issues that would make the page feel broken vs. merely
imperfect, and give the fix for each.
```

### 1.7 Accessibility compliance (WCAG 2.1 AA)

```
Run a WCAG 2.1 AA accessibility review of {URL / this HTML}. Check:
- Color contrast (text and UI components)
- Keyboard navigability and visible focus states
- Semantic HTML / landmark structure / heading order
- Alt text and non-text content
- Form labels, error identification, and instructions
- Touch target size, motion/animation safety (prefers-reduced-motion),
  and text resize behavior

For each issue give: the WCAG success criterion, the severity, where it occurs,
and a concrete code-level fix. End with the top 5 to fix first.
```

> Tip: this codebase has a dedicated `accessibility-review` skill — for a deeper pass, ask your assistant to run that.

### 1.8 End-to-end user flow

```
Map the primary user flow for {goal, e.g. "sign up and complete onboarding"}
based on {these screens / this URL}. For each step list: the user's goal, what
the screen asks of them, friction points, and drop-off risks. Identify
unnecessary steps, redundant data entry, dead ends, and moments where the user
might not know what happens next. Propose a streamlined flow with the step
count reduced and the riskiest friction point eliminated.
```

### 1.9 5-second / first-impression test

```
You are a first-time visitor. You can look at this screen for 5 seconds only,
then I take it away. {Screenshot.}

Now answer from memory: What is this product? What can I do here? What stood out?
What did you NOT notice? Was the main action obvious? Then tell me what to change
so the answers to those questions would be unambiguous after 5 seconds.
```

### 1.10 Competitive / heuristic benchmark

```
Compare my screen ({screenshot/URL}) against the conventions of best-in-class
{category, e.g. "fintech dashboards" / "indie game landing pages"}. Where does
mine deviate from established patterns in ways that help vs. hurt? Which
conventions am I missing that users will expect? Give me a "keep / fix / steal"
list: what's working, what's broken, and what to borrow from the best.
```

---

## Part 2 — UI Improvement Prompts

Audit tells you what's wrong; these generate the fixes.

### 2.1 Layout optimization

```
Redesign the layout of {this screen} for clarity and focus. Keep the same
content and brand, but improve the structure. Consider: a clearer grid,
better content grouping (proximity), a more deliberate F- or Z-pattern for
scanning, and a stronger above-the-fold. Give me 2 distinct layout directions
described concretely (sections, order, what's emphasized), and note the
trade-offs of each. {Attach current layout.}
```

### 2.2 Button & CTA placement

```
Audit every button and CTA on {this screen}. For each, tell me: is it visually
weighted correctly for its importance (primary/secondary/tertiary)? Is the label
action-oriented and specific ("Start free trial" > "Submit")? Is the primary CTA
placed where the eye naturally arrives and repeated at logical scroll points?
Are there competing CTAs diluting the main action? Recommend a clear button
hierarchy, exact labels, and placement for the one action this page most wants
the user to take.
```

### 2.3 Whitespace & spacing rhythm

```
Evaluate the use of whitespace and spacing on {this screen}. Identify areas
that feel cramped or cluttered and areas with awkward/inconsistent gaps.
Propose a consistent spacing scale (e.g. a 4px or 8px base: 4/8/12/16/24/32/48/64)
and tell me specifically where to add breathing room and where to tighten.
Explain how better spacing alone would improve the perceived hierarchy and
quality.
```

### 2.4 Information architecture

```
Review the information architecture of {this page / this site map}. Is content
grouped in a way that matches how users think, or how the org is structured?
Are labels and categories clear? Is anything buried that should be surfaced, or
surfaced that should be buried? Propose a revised structure (a content outline
or sitemap) with clearer grouping and labels, and explain the reasoning for any
move.
```

### 2.5 Visual consistency sweep

```
Scan {these screens} for visual inconsistencies: mismatched button styles,
varying corner radii, inconsistent shadows, differing icon styles/weights,
one-off spacing values, near-duplicate colors, and typographic drift. List
every inconsistency you find, grouped by type, and give me the single canonical
value each should standardize to. The goal is a system, not a collection.
```

### 2.6 Component-level redesign

```
Redesign this single component: {paste the component / screenshot}. Keep its
function identical. Improve: visual hierarchy within the component, state
handling (default / hover / active / focus / disabled / loading / error /
empty), spacing, and affordance (does it look interactive?). Provide the
improved design as {a description / Tailwind classes / the JSX}, plus the full
set of states.
```

### 2.7 "Make it feel premium"

```
This screen works but feels {generic / dated / cheap / unfinished}: {screenshot}.
Without changing the content or core layout, tell me the specific craft-level
moves that would make it feel premium and modern — e.g. refined type, a tighter
spacing system, subtle depth/shadows, micro-interactions, better empty states,
purposeful motion. Give me a prioritized "polish checklist" of 8–12 concrete
changes, cheapest-highest-impact first.
```

---

## Part 3 — UX Enhancement Prompts

### 3.1 User journey mapping

```
Build a user journey map for {persona, e.g. "a first-time user evaluating
whether to sign up"} pursuing {goal}. For each stage (Awareness → Consideration
→ Onboarding → Activation → Retention, or stages you think fit better), capture:
the user's actions, their goal, their likely thoughts/emotions, friction points,
and opportunities to delight or reassure. Output as a table. Then highlight the
two stages where I'm most likely losing people and what to do about each.
```

### 3.2 Friction-point teardown

```
You are a conversion-focused UX strategist. Walk through {this flow: screens /
URL} as a skeptical, busy, slightly impatient user. Narrate every point of
friction: anything confusing, slow, redundant, anxiety-inducing (e.g. asking for
a credit card too early), or requiring unnecessary thought. Rank the friction
points by how many users they'd cost me. For the top 3, give a specific fix and
the principle behind it (Hick's law, recognition over recall, etc.).
```

### 3.3 Readability & scannability

```
Evaluate how scannable {this page} is for someone who will NOT read every word.
Assess: heading structure, paragraph length, use of bullets/lists, bolding of
key phrases, front-loading of important info, and visual anchors. Rewrite one
representative section to be maximally scannable while keeping the meaning, and
tell me the general rules to apply to the rest.
```

### 3.4 CTA & conversion optimization

```
Optimize {this page} for its primary conversion goal: {goal}. Analyze the value
proposition clarity, objection handling, social proof placement, CTA wording and
prominence, and the cognitive load of the ask. Suggest: a sharper above-the-fold
value statement, the ideal moments to place CTAs, what reassurance to add near
the action (guarantees, "no card required," etc.), and 3 alternative CTA copy
options to test.
```

### 3.5 Navigation structure redesign

```
Propose a more intuitive navigation structure for {site / app}. Here are the
main destinations users need: {list them}. Here are the top tasks users come to
do: {list them}. Design a nav (top-level items, grouping, labels, and the
pattern — top nav / sidebar / tab bar / mega-menu) that maps to tasks, minimizes
depth, and uses plain language. Explain why this structure beats {current}.
```

### 3.6 Onboarding & empty states

```
Design the onboarding and empty-state experience for {feature/app}. For a brand-
new user with no data yet, what should each empty state say and offer so it
guides action instead of looking broken? What's the minimum first-run flow to
get them to their first "aha" moment fastest? Give me copy + layout for the 3
most important empty states and a lean onboarding sequence.
```

### 3.7 Microcopy & UX writing

```
Review and rewrite the UX copy on {this screen}. Tighten button labels, form
hints, error messages, tooltips, and empty states. Make them clear, human, and
confidence-inspiring — no jargon, no dead-end errors (every error says what
happened and what to do next). Give me a before/after table for each string.
Tone: {e.g. "friendly and plain" / "precise and trustworthy"}.
```

> Tip: this codebase has a dedicated `ux-copy` skill for microcopy, error messages, empty states, and CTAs.

### 3.8 Cognitive load reduction

```
Analyze {this screen} for cognitive load. Where am I making the user think,
remember, compare, or decide more than necessary? Apply Hick's law (too many
choices), Miller's law (too much to hold in memory), and recognition-over-recall.
Tell me what to remove, defer, group, or set as a smart default to make the
screen feel effortless. Rank by how much mental effort each change saves.
```

---

## Part 4 — Design Variations & A/B Testing Prompts

### 4.1 Generate distinct design directions

```
Generate 3 genuinely distinct design directions for {this screen}, not 3 minor
variations. For each, give it a name and a one-line concept (e.g. "Editorial &
calm," "Bold & high-contrast," "Dense & data-forward"), then describe the
layout, type treatment, color emphasis, and motion approach. Tell me which
audience and brand each direction suits best, and the risk of each.
```

### 4.2 A/B test hypothesis backlog

```
You are a growth/experimentation lead. For {this page} with the goal of
{metric, e.g. "increase signup conversion"}, generate a backlog of 10 A/B test
ideas. For each, state: the hypothesis ("If we ___, then ___ because ___"), the
specific change, the primary metric, the expected effect size (rough), and the
implementation effort (S/M/L). Sort by impact-to-effort. Flag which 2 I should
run first and why.
```

### 4.3 Single-variable variant generator

```
I want to A/B test {one element, e.g. "the hero headline" / "the CTA color" /
"the pricing layout"}. Generate {5} meaningfully different variants for ONLY
that element, holding everything else constant. For each, explain the
psychological angle it's testing (urgency, clarity, social proof, simplicity,
etc.) and what a win would tell me about my users.
```

### 4.4 Headline & value-prop variations

```
Write 8 variations of the hero headline + subheadline for {product}. The
audience is {who}; the core value is {what}; the tone is {how}. Range across
angles: outcome-focused, problem-focused, curiosity, bold claim, plainspoken,
and playful. Keep headlines under ~10 words. Then tell me which 3 you'd test
first and the reasoning.
```

### 4.5 Critique a variation objectively

```
Here are two versions of {screen}: A {attach} and B {attach}. Without knowing
which I prefer, evaluate both on hierarchy, clarity, conversion potential, and
craft. Call a winner per dimension, name the single biggest weakness of each,
and propose a "C" that combines the strengths of both.
```

---

## Part 5 — Style Guides & Design Systems Prompts

### 5.1 Extract design tokens from existing UI

```
From {these screenshots / this CSS / this URL}, reverse-engineer a design-token
system. Produce: a color palette (semantic names + hex, including states), a
type scale (roles, sizes, weights, line-heights), a spacing scale, radii,
shadows/elevation, and border styles. Where the current UI is inconsistent,
pick the best canonical value and note what it replaces. Output as a clean token
list I could drop into {CSS variables / a Tailwind config / a tokens.json}.
```

### 5.2 Build a design system from scratch

```
Help me define a design system for {product} with a {adjective, e.g. "modern,
energetic, precise"} personality. Cover: brand foundations (voice, mood,
keywords), color system (palette + semantic roles + dark mode), typography
(typefaces + full scale), spacing/layout grid, elevation/shadows, iconography
style, and motion principles. For each, give concrete values and a one-line
rationale tied to the personality. Keep it lean enough for a small team to
actually maintain.
```

### 5.3 Component documentation

```
Write design-system documentation for the {component, e.g. "Button"} component.
Include: purpose and when to use it, all variants (primary/secondary/ghost/
destructive…), all states (default/hover/active/focus/disabled/loading), sizes,
do's and don'ts with examples, accessibility notes (roles, keyboard, contrast),
and the props/anatomy. Format it like a real design-system page.
```

> Tip: this codebase has a dedicated `design-system` skill for auditing, documenting, and extending systems, and a `design-handoff` skill for engineering spec sheets.

### 5.4 Consistency linter

```
Act as a design-system linter. Here are {N} screens / components: {attach}.
Find every place that deviates from a consistent system — ad hoc colors, off-
scale spacing, inconsistent radii/shadows, typographic drift, mismatched
component styles. Output a table: location | what's inconsistent | the canonical
value it should use. Then summarize the 5 system rules that, if enforced, would
eliminate most of the drift.
```

### 5.5 Naming & token taxonomy

```
Review my design-token names: {paste}. Are they semantic and scalable, or tied
to specific values (e.g. "blue-500" vs "color-action-primary")? Propose a clean,
tiered naming taxonomy (primitive tokens → semantic tokens → component tokens)
with examples, so the system can re-theme without renaming everything. Show how
a light/dark theme swap would work under this scheme.
```

### 5.6 Design-to-dev handoff spec

```
Produce an engineering handoff spec for {this component/screen}. Include: exact
spacing, sizing, and layout (with values), the design tokens used, every
interaction state, responsive behavior at each breakpoint, edge/empty/error
cases, animation timing and easing, and accessibility requirements. Format so a
developer could build it without guessing.
```

---

## Part 6 — Three.js & Modern Animation Prompts

This is where a site goes from "clean" to "memorable." The throughline: **motion must serve clarity, not fight it.** As a game designer you already think in terms of feel, timing, and feedback — these prompts translate that instinct to the web. Every prompt here assumes performance and `prefers-reduced-motion` are non-negotiable.

### 6.1 Decide WHERE 3D/animation earns its place

```
You are a motion designer with a strong taste for restraint. Here is my site:
{describe / screens / URL}. Tell me where 3D (Three.js) and animation would
genuinely elevate the experience vs. where they'd be noise that hurts
performance and clarity. Categorize each candidate moment as: "hero/signature
moment," "supporting micro-interaction," "transition/continuity," or "skip it."
Give me a ranked shortlist of the 3 highest-impact places to invest motion
effort, and what NOT to animate.
```

### 6.2 Three.js hero scene concept

```
Design a Three.js hero scene for {product, personality: "___"}. Propose 3
distinct concepts (e.g. "floating low-poly objects with parallax," "an
interactive particle field that reacts to the cursor," "a slowly rotating
abstract geometry with depth-of-field"). For each: the visual idea, how it ties
to the brand, the interaction model (mouse/scroll/idle), the rough technical
approach (geometry, materials, lighting, post-processing), and a realistic
performance budget. Recommend one and explain why it fits.
```

### 6.3 Three.js hero — implementation

```
Implement the {chosen concept} as a self-contained Three.js hero for the web.
Requirements:
- Stack: {plain Three.js / react-three-fiber + drei}.
- Responsive: looks right from 375px to ultrawide; resizes cleanly.
- Performance: target 60fps on a mid laptop; cap pixel ratio; pause the render
  loop when off-screen (IntersectionObserver) and when the tab is hidden.
- Respect prefers-reduced-motion: fall back to a static, attractive frame.
- Graceful degradation if WebGL is unavailable.
- Clean teardown (dispose geometries/materials/textures; cancel RAF) to avoid
  leaks in an SPA.
Give me the complete, commented code plus notes on where to tune the feel.
```

### 6.4 Scroll-driven animation

```
Design a scroll-driven animation sequence for {page/section}. I want
{e.g. "elements that assemble as you scroll," "a 3D object that rotates with
scroll progress," "pinned sections with staged reveals"}. Specify: the trigger
points, what animates at each, easing and duration, and how to keep it smooth
(transform/opacity only, will-change discipline, no layout thrash). Recommend
the tool ({GSAP ScrollTrigger / Framer Motion / Motion One / IntersectionObserver
+ CSS}) and justify it. Include reduced-motion fallbacks.
```

### 6.5 Micro-interactions & feedback

```
You are designing the "feel" of {component/UI}, the way a game designer tunes
game feel. Specify a set of micro-interactions: hover, press, focus, success,
error, loading, and state transitions. For each give: what moves, the timing
(ms) and easing curve, and the principle (anticipation, follow-through,
overshoot, settle). Keep it tasteful and fast — nothing over ~300ms for UI
feedback. Provide it as a spec I can hand to a dev, with suggested
Framer-motion / CSS values.
```

### 6.6 Page & element transitions

```
Design the transition system for {site/app}: page-to-page transitions, modal
open/close, list item enter/exit, and shared-element continuity where it makes
sense. Define a consistent motion language: a small set of durations (e.g.
fast 150ms / base 250ms / slow 400ms), 2–3 standard easings, and rules for when
to use each. Show how to keep transitions from feeling slow (perceived
performance: animate out fast, in a touch slower; never block input). Include
reduced-motion behavior.
```

### 6.7 Motion design system / tokens

```
Create a motion design system for {product}. Define motion tokens: a duration
scale, an easing set (with cubic-bezier values and when to use each: standard,
decelerate, accelerate, spring), distance/displacement guidelines, and stagger
rules. Establish principles (purposeful, consistent, fast, respectful of
reduced-motion). Output as tokens I can codify (CSS variables / a JS config) so
all animation across the site stays coherent.
```

### 6.8 Three.js performance audit

```
Audit this Three.js / WebGL scene for performance: {paste code / describe}.
Check: draw calls and geometry merging/instancing, material and texture cost,
overdraw, pixel ratio handling, render-loop efficiency (is it rendering when
nothing changes?), post-processing cost, memory disposal, and mobile/GPU
fallbacks. Give me a prioritized optimization list with the expected fps/quality
trade-off of each, and what to cut first if I'm over budget on low-end devices.
```

### 6.9 Tasteful-vs-gimmick gut check

```
Be my taste filter. Here's a motion/3D idea I'm considering for {context}:
{describe}. Pressure-test it: Does it serve the user or just show off? Will it
still feel good on the 50th visit, or only the 1st? Does it slow down someone
who's trying to get something done? Does it hurt accessibility or performance?
Give me a verdict (ship / tone down / cut), and if "tone down," the restrained
version that keeps 80% of the delight at 20% of the cost.
```

### 6.10 Loading & perceived-performance choreography

```
Design the loading and first-paint experience for a motion-heavy / Three.js
page so it never feels slow. Cover: what to show during asset load (skeletons,
a minimal branded loader, progressive reveal), how to sequence the entrance so
the page feels alive the instant it's interactive, lazy-loading the heavy 3D
after first paint, and avoiding layout shift. Give me the choreography as a
timeline (0ms → interactive) with what appears when.
```

---

## Tailored Section — Prompts for Your Stack

Pre-filled for your environment: **React 18 + TypeScript (strict), Tailwind + shadcn/ui (Radix primitives), Zustand, recharts, reactflow, framer-motion**, and a game-designer's eye for feel and polish. Paste component code or screenshots from your app and these will produce output you can use almost verbatim.

### T.1 Review a shadcn/Tailwind component

```
You are a senior React/TypeScript design engineer. Review this component from
my app — React 18, strict TS, Tailwind, shadcn/ui (Radix), framer-motion.

{paste the .tsx}

Critique: visual hierarchy, spacing rhythm (against an 8px scale), state
coverage (default/hover/focus-visible/active/disabled/loading/error/empty),
accessibility (Radix is in use — am I preserving its a11y?), and dark-mode
correctness. Then return the improved component as a drop-in replacement using
Tailwind utility classes and shadcn conventions, with framer-motion for any
motion. Keep it strict-TS clean. Note what you changed and why.
```

### T.2 Tailwind design tokens / theme audit

```
Here is my Tailwind theme config / CSS variables: {paste}. Audit it as a design
system: are my colors semantic (background/foreground/primary/muted/accent/
destructive…) and dark-mode-ready in the shadcn CSS-variable style? Is there a
coherent spacing, radius, and shadow scale, or one-off values leaking into
components? Propose a cleaned-up theme (the CSS-variable block + tailwind.config
extensions) and flag the top component-level cleanups to match it.
```

### T.3 Framer-motion micro-interaction spec

```
Design micro-interactions for {component} in my React app using framer-motion.
I care about game-feel: anticipation, snappy response, a satisfying settle. For
each interaction (mount, hover, tap, layout change, exit) give me the exact
framer-motion props (variants, transition with type/stiffness/damping or
duration/ease) and keep UI feedback under ~250ms. Provide the code, and a
reduced-motion variant gated on useReducedMotion(). Tasteful, not bouncy-toy.
```

### T.4 Add a Three.js / R3F moment to my React app

```
I want to add a tasteful 3D moment to my React 18 + TypeScript app using
react-three-fiber + drei (and framer-motion for surrounding UI). Context:
{where it goes, the brand feel}. Propose the concept, then give me a
self-contained <Scene/> component that: is strict-TS typed, responsive, caps
pixel ratio, pauses when off-screen and on hidden tab, disposes resources on
unmount, falls back to a static frame under prefers-reduced-motion, and
degrades if WebGL is missing. Comment the knobs I'd tune for feel.
```

### T.5 recharts / data-viz polish

```
Review this recharts chart in my React/TS + Tailwind app: {paste}. As a data-viz
designer, improve: clarity of the story it tells, color (use my semantic theme
tokens, colorblind-safe), axis/label/gridline restraint, tooltip usefulness,
empty/loading states, and subtle entrance animation that aids comprehension
rather than distracting. Return the improved component and explain the viz
decisions.
```

### T.6 reactflow graph UX

```
I visualize a node graph with reactflow in my app: {paste / screenshot}.
Improve its UX and visual design: node hierarchy and readability, edge clarity,
handle affordances, zoom/pan discoverability, selection/hover feedback, and how
it scales as the graph grows. Suggest a clean node-style system (consistent
sizing, color-coded by type using my theme tokens) and tasteful motion for
state changes. Keep it legible at a glance.
```

### T.7 Game-designer crossover: bring "juice" to the web tastefully

```
I'm a game designer applying game-feel principles to a productivity web app
(React/TS, Tailwind, framer-motion). I want the app to feel responsive and alive
without being gimmicky or slowing users down. Map game-feel concepts — feedback,
anticipation, follow-through, easing, juicy confirmation, screen-space feedback —
onto specific, restrained web interactions for {feature}. For each, give the
principle, the web translation, exact timing/easing, and a "too far" warning so
it stays professional. Code where useful.
```

---

## Appendix — Reusable Variables & Workflow Recipes

### Fill these once, reuse everywhere

Keep a small block like this at the top of your notes and paste it into prompts so the AI always has context:

```
PRODUCT: {name + one-line description}
AUDIENCE: {who uses it}
BRAND PERSONALITY: {3 adjectives}
PRIMARY GOAL OF THIS PAGE: {the one action/metric}
STACK: {e.g. React 18 + TS, Tailwind, shadcn/ui, framer-motion, three.js/R3F}
CONSTRAINTS: {dark mode required, WCAG AA, 60fps, etc.}
TONE OF COPY: {e.g. friendly + plain}
```

### Recipe A — Full page overhaul (start to finish)

1. **Audit** with 1.1 (master), then drill in with 1.2–1.8 on whatever scored low.
2. **Prioritize** — ask: *"From all findings, give me the ranked top 7 by impact-to-effort."*
3. **Fix** with the relevant Part 2 / Part 3 prompts, one issue at a time.
4. **Vary** with 4.1 to explore directions, 4.2 to build a test backlog.
5. **Systematize** with 5.1 (extract tokens) so fixes don't drift back.
6. **Add motion** with Part 6 — but run 6.1 first to decide where it earns its place.
7. **Hand off** with 5.6 or T.4 for implementation.

### Recipe B — Just make this one screen better

1. 1.1 master audit on the screen → 2.7 "make it premium" polish checklist → 6.5 micro-interactions → 4.5 to compare your before/after.

### Recipe C — Establish a design system

1. 5.1 extract tokens from current UI → 5.5 fix the naming taxonomy → 5.2 fill the gaps → 6.7 add motion tokens → 5.4 linter pass across all screens to enforce it.

### Recipe D — Add a signature 3D moment

1. 6.1 decide where → 6.2 concepts → pick one → 6.3 (or T.4 for R3F) implement → 6.8 performance audit → 6.9 taste gut-check → 6.10 loading choreography.

### Two skills already in this workspace worth invoking

Your environment includes design skills you can ask your assistant to run directly instead of prompting from scratch: **design-critique**, **accessibility-review**, **design-system**, **design-handoff**, **ux-copy**, **user-research**, and **research-synthesis**. When a task matches one of these, ask for it by name — e.g. *"run the accessibility-review skill on this page"* — for a deeper, structured pass than a one-off prompt.

---

*Built for systematic, repeatable design improvement. Treat every prompt as a starting template, always ground the AI in a real artifact, and always ask it to prioritize. The goal is a system you return to — not a one-time critique.*
