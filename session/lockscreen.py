#!/usr/bin/env python3
"""Draw the lock screen's background as a Minecraft screen.

The lock screen cannot be *in* Minecraft — credentials never go through the
game client, which is the one rail this project does not bend. But every
lock program here displays a background image and draws very little of its
own. So the screen around what it draws is rendered here, out of Minecraft's
own textures, in the shape of the Direct Connection screen: tiled dirt, a
title, a label, a text field, and two buttons.

Nothing is invented. The background tile, the button sprite and the font come
out of the installed client jar, and the text field is the two filled
rectangles `TextFieldWidget` draws. The result is Minecraft's screen with
Minecraft's pixels in it, at Minecraft's own GUI scale for this monitor.

Prints the layout back as `NAME=<integer>` lines for the caller to eval:
where the text field ended up, and where a ring would go inside it. hyprlock
draws a real field over that rectangle, so `--no-field` leaves the drawn one
out; swaylock cannot, so it keeps the drawn field and puts its ring in the
middle of it, where it reads as that field's cursor.

Exits non-zero if the client jar cannot be found or read, which is the signal
to fall back to a plainer screen. A lock screen that will not draw must still
lock.
"""

from __future__ import annotations

import argparse
from zipfile import ZipFile

from mcpixels import Surface, decode, find_jar, gui_scale, load_font

#: The real dirt block, which is what the menu background has always been.
#: `gui/menu_background.png` in 1.21 is a flat black overlay, not a picture.
BACKGROUND = "assets/minecraft/textures/block/dirt.png"
BUTTON = "assets/minecraft/textures/gui/sprites/widget/button_disabled.png"


# --- the screen --------------------------------------------------------------

WHITE = (0xFF, 0xFF, 0xFF)
LABEL = (0xA0, 0xA0, 0xA0)
#: TextFieldWidget's own two rectangles: a border, and black inside it.
BORDER = (0xFF, 0xFF, 0xFF)
INSIDE = (0x00, 0x00, 0x00)
#: How far the dirt is darkened. Vanilla's options background tinted it by
#: 0x404040 — a quarter — and then laid a black overlay over the top; a single
#: multiply lands in the same place with one pass instead of two.
SHADE = 0.30

FIELD_W, FIELD_H = 200, 20
BUTTON_W, BUTTON_H = 200, 20


def render(width: int, height: int, out: str, title: str, label: str,
           primary: str, secondary: str, field: bool = True) -> dict[str, int]:
    jar = find_jar()
    if jar is None:
        raise SystemExit("no Minecraft client jar found")

    with ZipFile(jar) as zf:
        _, _, background = decode(zf.read(BACKGROUND))
        _, _, button = decode(zf.read(BUTTON))
        font = load_font(zf)

    scale = gui_scale(width, height)
    gh = height // scale

    canvas = Surface(width, height)
    # Two GUI pixels per texel and 32 GUI pixels per tile, as Screen does it.
    canvas.tile(background, scale * 2, SHADE)

    # Laid out in device pixels rather than GUI ones, because a lock program
    # that draws its own field puts it in the middle of the screen and the
    # label above it has to line up with that, not with the middle of a GUI
    # grid that may be half a pixel off it.
    field_x = (width - FIELD_W * scale) // 2
    field_y = round(gh * 0.35) * scale
    title_y = round(gh * 0.07) * scale
    first_y = round(gh * 0.58) * scale
    second_y = round(gh * 0.65) * scale

    font.draw(canvas, title, (width - font.width(title) * scale) // 2,
              title_y, scale, WHITE)
    font.draw(canvas, label, field_x, field_y - 12 * scale, scale, LABEL)

    # Drawn only when whatever locks the screen cannot draw a field of its
    # own. hyprlock can, and its is the one you can type into.
    if field:
        canvas.fill(field_x - scale, field_y - scale,
                    (FIELD_W + 2) * scale, (FIELD_H + 2) * scale, BORDER)
        canvas.fill(field_x, field_y, FIELD_W * scale, FIELD_H * scale, INSIDE)

    for text, y in ((primary, first_y), (secondary, second_y)):
        canvas.blit(button, field_x, y, scale)
        font.draw(canvas, text,
                  field_x + (BUTTON_W - font.width(text)) // 2 * scale,
                  y + (BUTTON_H - 8) // 2 * scale, scale, LABEL)

    canvas.write(out)

    return {
        "SCALE": scale,
        "SCREEN_W": width,
        "SCREEN_H": height,
        # The field, in device pixels, for a lock program to draw its own on
        # top of. Exactly centred horizontally, which is what lets it be
        # placed with a plain `halign = center`.
        "FIELD_X": field_x,
        "FIELD_Y": field_y,
        "FIELD_W": FIELD_W * scale,
        "FIELD_H": FIELD_H * scale,
        # Where swaylock's ring goes instead: the middle of the field, so it
        # reads as the cursor of the box you are typing into rather than as
        # chrome of its own.
        "RING_X": width // 2,
        "RING_Y": field_y + FIELD_H * scale // 2,
        "RING_RADIUS": 7 * scale,
        "RING_THICKNESS": 2 * scale,
        "FONT_SIZE": 4 * scale,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--height", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="Session Locked")
    ap.add_argument("--label", default="Password")
    ap.add_argument("--primary", default="Press Enter to Unlock")
    ap.add_argument("--secondary", default="")
    ap.add_argument("--no-field", dest="field", action="store_false",
                    help="leave the text field out, for a lock screen that "
                         "draws a real one of its own")
    args = ap.parse_args()

    geometry = render(args.width, args.height, args.out,
                      args.title, args.label, args.primary, args.secondary,
                      field=args.field)
    # `NAME=<integer>` a line, so the caller can eval it. Every value is an
    # int and nothing here is ever quoted or expanded.
    for name, value in geometry.items():
        print(f"{name}={int(value)}")


if __name__ == "__main__":
    main()
