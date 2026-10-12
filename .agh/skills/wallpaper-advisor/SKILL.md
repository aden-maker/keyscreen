---
name: wallpaper-advisor
description: Pick or recommend a KeyScreen wallpaper, accent colour and key opacity for the current app, mood or time of day, then apply it through the keyscreen-01 MHS device.
---

# Wallpaper advisor

You drive the KeyScreen touch keyboard (MHS device `keyscreen-01`) with the Agnes model only.

1. `call_device keyscreen-01 list_wallpapers` to see stored wallpapers, the active profile and its theme.
2. If the user attached an image or asked for a style, inspect the candidates (`preview_layout` returns a screenshot URL) and judge:
   - Legibility: the key legends are light text on dark keys. Prefer darker or low-detail images, or raise `opacity` (170–230) on busy images.
   - Accent colour (`theme`, `#rrggbb`): take a saturated colour from the wallpaper so key borders match it.
   - Fit: coding means calm and dark; design means colourful; games mean high contrast.
3. Apply it with `set_wallpaper {wallpaper, profile, theme, opacity}`. Only use names returned by `list_wallpapers`; uploading happens in the desktop panel.
4. Reply in one or two sentences: what you chose and why. Offer one alternative.

Never invent wallpaper names. If none fit, ask the user to upload one in the desktop panel (http://127.0.0.1:43125).
