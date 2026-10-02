# Self-hosted web fonts

JetBrains Mono, Instrument Sans and Unbounded, vendored so the site loads no
fonts from a third party. This is what allows nginx to serve a
`font-src 'self'` CSP without losing the site's typography; before this, both
stylesheets `@import`ed `fonts.googleapis.com` and the admin panel `<link>`ed
it a second time.

The `@font-face` declarations that use these files live in
`frontend/public/css/fonts.css`, which is linked from `index.html` and
`admin/index.html`. Nothing else should reference these files directly.

## Provenance

JetBrains Mono was retrieved 2026-08-30 from Google Fonts, which is the same
source the site used before, so the bytes are the ones production was already
serving:

    https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap

Instrument Sans and Unbounded were retrieved 2026-09-26 for the Reflection
redesign (`docs/design/2026-09-25-reflection-redesign.md`), from:

    https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Unbounded:wght@600;700&display=swap

Only that response's `latin` and `latin-ext` blocks were kept: these two faces
set the site's own copy, which is English.

Both requests were fetched with a current desktop Chrome User-Agent, which is
what makes Google return WOFF2. The CSS it returns names one file per
family+subset; those files were downloaded unmodified and renamed from Google's
opaque hashes to `<family>-<subset>.woff2`. No re-subsetting, re-compression or
other modification was performed.

| Family | Version | Axes | Weights used by this site |
|---|---|---|---|
| JetBrains Mono | 2.211 | `wght` 400-800 (variable) | 400, 500 |
| Instrument Sans | 1.000 (gftools[0.9.28]) | `wght` 400-700 (variable) | 400, 500, 600 |
| Unbounded | 1.701 (gftools[0.9.28.dev5+ged2979d]) | `wght` 200-900 (variable) | 600, 700 |

All three are **variable** fonts: one file per subset covers every weight. The
per-weight `@font-face` blocks in `fonts.css` all point at the same file.

## Licensing

All three families are under the SIL Open Font License 1.1, which permits
redistribution provided the license travels with the fonts:

* `LICENSE-JetBrainsMono.txt` - from https://github.com/JetBrains/JetBrainsMono (`OFL.txt`)
* `LICENSE-InstrumentSans.txt` - from https://github.com/google/fonts at commit 23e54b51ddffbc7713c583748e3bd86f62b1fa4a (`ofl/instrumentsans/OFL.txt`)
* `LICENSE-Unbounded.txt` - from https://github.com/google/fonts at commit 23e54b51ddffbc7713c583748e3bd86f62b1fa4a (`ofl/unbounded/OFL.txt`)

No family's copyright line declares a **Reserved Font Name**, so Google's
subset builds may keep their names, and we may redistribute them under those
names. The license URL embedded in each binary's name table (ID 14) confirms
OFL for all three.

## Caching caveat

nginx serves `*.woff2` with `expires 7d; Cache-Control: public, immutable`
(the fonts-and-images location in `nginx/sites/production/production.conf`)
and these filenames carry **no content hash**. A client that has cached a file
will not revalidate it for seven days and cannot be forced to. So do not
replace a file in place: if a font ever needs to change, give it a new filename
(or add a version suffix) and update `fonts.css` in the same commit.

## Regenerating

    curl -A "<current desktop Chrome UA>" \
      "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap"

    curl -A "<current desktop Chrome UA>" \
      "https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Unbounded:wght@600;700&display=swap"

Download each `url()` from the responses and rename it to
`<family>-<subset>.woff2`. A file whose bytes differ from one already shipped
takes a new name instead, such as a version suffix (see the caching caveat
above). In the CSS, rewrite the `url()`s to `/fonts/` and re-indent the blocks
to four spaces, like the rest of `fonts.css`. From the second response keep
only the blocks under `/* latin */` and `/* latin-ext */`. Nothing else in the
returned CSS should be altered. List every new file's checksum below.

## Checksums (SHA-256)

```
21fac8da552a915e7a9fb84c5afaeb85d35507b2616346d592e78128c1cfe3e0  instrument-sans-latin-ext.woff2
6219bc4bfdfc5d9b2201dcdf046218b122a758f932e25ed5f168f929b7ca2311  instrument-sans-latin.woff2
9343de2ca5d9549f792e7962375af8efb0f320c7643bfd36c884b5a30e5c396f  jetbrains-mono-cyrillic-ext.woff2
4995a9a43ac659ec32fcd8b463755cd6a07b31a6e6b3894a6a153b661cf490e2  jetbrains-mono-cyrillic.woff2
49c3da6c9a2b279b0f1f860f5cfb1f5dc38d88a5c7be9c9b1837bbc4e3db6111  jetbrains-mono-greek.woff2
9c38cb2d0d2d93c1ee6e21fa78db76f13ea7e15e15cc64214c7ca89b6aaa35c4  jetbrains-mono-latin-ext.woff2
2c32b9b3ee358c119e210f6f5195f9bd34894d78a785ff2e95d60e718e400af4  jetbrains-mono-latin.woff2
d44eb1936043a56038eb02dd70b243f379bef65783f94ec12f277550720411f1  jetbrains-mono-vietnamese.woff2
ed84482df7b95e6a56a113de1ba2a8d54337f499ba19d54ca697a7e15427ff5f  unbounded-latin-ext.woff2
d7f07f8a308ce0a7287d79a65a85cfbc0f4741ef426bf1a3902d24392cc71723  unbounded-latin.woff2
```
