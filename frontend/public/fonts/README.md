# Self-hosted web fonts

Inter and JetBrains Mono, vendored so the site loads no fonts from a third
party. This is what allows nginx to serve a `font-src 'self'` CSP without
losing the site's typography; before this, both stylesheets `@import`ed
`fonts.googleapis.com` and the admin panel `<link>`ed it a second time.

The `@font-face` declarations that use these files live in
`frontend/public/css/fonts.css`, which is linked from `index.html` and
`admin/index.html`. Nothing else should reference these files directly.

## Provenance

Retrieved 2026-08-30 from Google Fonts, which is the same source the site used
before, so the bytes are the ones production was already serving:

    https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap

Fetched with a current desktop Chrome User-Agent, which is what makes Google
return WOFF2. The CSS it returns names one file per family+subset; those files
were downloaded unmodified and renamed from Google's opaque hashes to
`<family>-<subset>.woff2`. No re-subsetting, re-compression or other
modification was performed.

| Family | Version | Axes | Weights used by this site |
|---|---|---|---|
| Inter | 4.001 (git-66647c0bb) | `wght` 100-900 (variable) | 300, 400, 500, 600, 700 |
| JetBrains Mono | 2.211 | `wght` 400-800 (variable) | 400, 500 |

Both are **variable** fonts: one file per subset covers every weight. The
per-weight `@font-face` blocks in `fonts.css` all point at the same file.

## Licensing

Both families are under the SIL Open Font License 1.1, which permits
redistribution provided the license travels with the fonts:

* `LICENSE-Inter.txt` - from https://github.com/rsms/inter (`LICENSE.txt`)
* `LICENSE-JetBrainsMono.txt` - from https://github.com/JetBrains/JetBrainsMono (`OFL.txt`)

Neither copyright line declares a **Reserved Font Name**, so Google's subset
builds may keep the names `Inter` and `JetBrains Mono`, and we may
redistribute them under those names. The license URL embedded in each binary's
name table (ID 14) confirms OFL for both.

## Caching caveat

nginx serves `*.woff2` with `expires 7d; Cache-Control: public, immutable`
(`nginx/sites/default.conf:181`) and these filenames carry **no content hash**.
A client that has cached a file will not revalidate it for seven days and
cannot be forced to. So do not replace a file in place: if a font ever needs to
change, give it a new filename (or add a version suffix) and update
`fonts.css` in the same commit.

## Regenerating

    curl -A "<current desktop Chrome UA>" \
      "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"

Download each `url()` from the response, rename to `<family>-<subset>.woff2`,
and rewrite the `url()`s in `fonts.css` to `/fonts/`. Nothing else in the
returned CSS should be altered. Re-verify the checksums below change as
expected, and re-run the rendering comparison.

## Checksums (SHA-256)

```
fccca918fea40089dacadc7045861314d1a6bc91f1f323cc1eeb22ebcdb321b5  inter-cyrillic-ext.woff2
aebf2ab4a4ce6810d73c1ac7be7cafb4e5ec4cee2d6db5fb3e09691747ec4bd6  inter-cyrillic.woff2
a2e2c783ca6f9c20486e81e72a279203e86730bbf8f01ff6a5ee9dbd09e1c271  inter-greek-ext.woff2
46dd4cdca58c26ae87cc6927657bf83b2e8abfc39ffd0ab176e301a8d28d22bf  inter-greek.woff2
a28eb6d3ccb534ae0c94ca999371df024aab60b08c3c8a5720ee9e32fa0faaa2  inter-latin-ext.woff2
c940764593d0fe5d596be327ca7558855e018039fb78509aa21921fd3644c3e4  inter-latin.woff2
8db00ff46c67b22cda8bed865acf7077651cac8d2841d5b40980556b48961931  inter-vietnamese.woff2
9343de2ca5d9549f792e7962375af8efb0f320c7643bfd36c884b5a30e5c396f  jetbrains-mono-cyrillic-ext.woff2
4995a9a43ac659ec32fcd8b463755cd6a07b31a6e6b3894a6a153b661cf490e2  jetbrains-mono-cyrillic.woff2
49c3da6c9a2b279b0f1f860f5cfb1f5dc38d88a5c7be9c9b1837bbc4e3db6111  jetbrains-mono-greek.woff2
9c38cb2d0d2d93c1ee6e21fa78db76f13ea7e15e15cc64214c7ca89b6aaa35c4  jetbrains-mono-latin-ext.woff2
2c32b9b3ee358c119e210f6f5195f9bd34894d78a785ff2e95d60e718e400af4  jetbrains-mono-latin.woff2
d44eb1936043a56038eb02dd70b243f379bef65783f94ec12f277550720411f1  jetbrains-mono-vietnamese.woff2
```
