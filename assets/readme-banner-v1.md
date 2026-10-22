# README banner - readme-banner-v1.jpg

Asset: `assets/readme-banner-v1.jpg` (1408x469, 3:1)

Tool/model: xAI Grok CLI, built-in `image_gen` tool, plus local compositing.

Generated as candidate `v1_hpckit`; the rejected alternative is kept in the brand
archive alongside its own prompt.

## Subject prompt

```text
A single continuous swirling vortex flow field, drawn in exquisitely fine cyan and teal streamline hairlines, divided into a small number of large rectangular tiles by a few very thin dividing lines. Each tile is displaced by a tiny amount from its neighbours, as though each were computed separately. Along the seams where tiles touch, and only there, a narrow band of hot coral marks the exchanged edge.
```

## The exact payload sent to the model

```text
Use your image_gen tool ONE time. Generate this image: A single continuous swirling vortex flow field, drawn in exquisitely fine cyan and teal streamline hairlines, occupying the centre and right of the frame and fading into darkness toward the left. The field is divided into a small number of large rectangular tiles — about six, no more — by a few very thin, very faint straight dividing lines. Each tile is displaced by a tiny amount from its neighbours, just one or two line-widths, so the streamlines almost but not quite line up where tiles meet, as though each tile were computed separately. Along those few seams where tiles touch, and ONLY there, a narrow band of hot coral glows softly, marking the exchanged edge. VERY IMPORTANT NEGATIVE CONSTRAINTS: do NOT draw a dense grid, graph paper, a lattice, a wireframe box, rungs, rails or a mesh of many cells. The dividing lines are few, thin and quiet; the flowing field is the subject and the divisions are a faint annotation over it. The LEFT THIRD of the frame is calm, dark and completely empty. Delicate hairlines throughout, most of the frame unlit. A stunning abstract scientific artwork, wide 2:1 landscape, for a premium software banner. RENDERING — this governs everything: rendered as exquisitely fine, delicate, hairline glowing lines and fine stippled luminous points. Atmospheric depth of field, volumetric glow, fine film grain, rich deep blacks and luminous highlights. Generous empty dark space; the artwork should feel sparse and restrained, with only a small fraction of the frame actually lit. Cinematic, elegant, refined, expensive, gallery-quality scientific data art. EXPLICITLY AVOID: thick or bold strokes, heavy lines, chunky shapes, neon, garish or oversaturated colour, poster-like flat high contrast, dense solid blocks of glow, a busy or crowded frame. Restraint and delicacy matter more than impact. FRAMING: the image will afterwards be cropped to a very wide 3:1 letterbox, keeping only the middle horizontal band. All important subject matter must sit within the central horizontal band, with generous empty dark margins along the top and bottom edges. Leave the LEFT THIRD dark, calm and completely empty as negative space — a wordmark goes there. PALETTE: a deep near-black charcoal ground with a cool blue cast, approximately #0D1116. Electric cyan and teal as the primary luminous colour, with a hot coral used sparingly on only a few selected features. NO amber, NO gold, NO orange-yellow, NO violet, NO purple, NO green, NO magenta, NO rainbow or spectral colourmaps. Full bleed: no border, no frame, no matte, no letterbox bars, no vignette ring. ABSOLUTELY NO TEXT: no letters, no words, no numbers, no axis labels, no tick marks, no logos, no watermarks, no signatures.
```

## Note on the palette gate

`_scripts/qc_new.py` rejects this artwork. 95.5% of its accent pixels fall in the coral band, against a family maximum of 69.9% (`dsgbr`) and a typical value of 7-21%. The palette specification makes cyan the primary luminous colour with coral "used sparingly on only a few selected features", so this banner inverts that hierarchy.

It was chosen anyway, deliberately, because the crossing coral seams read as rank boundaries better than the alternative candidate did. The measurement is recorded rather than suppressed: the other candidate, `v2_hpckit`, measured 34.8% and passed.

## The shared specification

Every banner in the openfluids family is generated from an identical
specification block; only the subject sentence changes per repository. The
`RENDERING`, `FRAMING` and `PALETTE` blocks used here are byte-identical to the
ones that produced the existing seven banners - verified before generating, not
assumed.

The `EXPLICITLY AVOID` clause exists because an earlier revision asked for
"thick", "bold", "punchy" and "very high contrast" artwork and got exactly that:
strokes 3-5 px, lit area up to 2.5x higher, accent saturation 177 against a
baseline of 126. Delicacy has to be stated, and its opposite has to be forbidden.

## Typography

The wordmark is **not** generated. Image models render short lowercase words
unpredictably, and accepting whatever letterforms come back is most of what makes
a generated banner look cheap. The artwork is generated deliberately textless and
the type is set locally:

- **Lato Light at 96 px**, constant across the whole family, tracking 6% of point
  size, ink `#F7F3EC`, left margin 82 px.
- Vertical placement by **optical centring**: the x-height band is centred on the
  frame midline. Measured at 233.5 px for this name, identical to every other
  banner in the family, so the wordmarks sit at the same apparent height despite
  differing ascenders and descenders.
- A small coral `openfluids` eyebrow sits above the repository wordmark.

## Grading

- Ground normalised to `#0D1116` through a shadow-weighted mask, with the black
  point estimated from the darkest 8% of pixels wherever they fall.
- Saturation lifted **only on the brightest accent cores** - a spike tip, a vortex
  centre - leaving the surrounding glow and the ground untouched.

Format: 1408x469 (3:1), JPEG quality 95, no chroma subsampling.
