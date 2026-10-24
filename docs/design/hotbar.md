# The hotbar

Real items in the slots, what each visual state means, and what a click on one does.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## Hotbar
- Slots are user-assigned by dragging apps from the catalog browser (creative-inventory
  style: click-to-pick-up, click-to-place — NOT HTML5-style drag).
- Slots are persistent and dense. Assignment stored in the daemon's config dir, not the
  world save.
- Lazy launch: an assigned slot whose app isn't running renders as a plain item;
  right-click launches it.
- **A running app with no slot borrows a free one.** Opening a `.md` file hands
  it to whatever `.desktop` claims that type, and that app was never assigned;
  so does reassigning a slot whose app is still open. Either way the hotbar
  would show what someone once chose rather than what is running, and an
  application would be open with nothing on screen admitting it. These
  *transient* slots are memory-only — an assignment is a choice, this is an
  observation — and behave like any other slot when clicked. With all nine
  assigned there is nowhere to put one; the daemon logs that rather than
  evicting a choice the user made.
- Hotbar is global across all Sway workspaces.
- **The slots hold real items** (M8). One registered item, `mcshell:app`, with
  the application in a component — registries freeze at startup and the catalog
  is found at runtime, so an item per `.desktop` file could never exist. This
  reverses the original decision that the hotbar was drawn over the vanilla one
  and the inventory stayed empty. That version could not show a hover name,
  could not put anything in your hand, and sat invisibly on top of any wood you
  picked up.
- **Still a rendering of daemon state.** Stacks are derived from every `taskbar`
  message; a click that moves one is reported, not applied. The daemon decides
  and its next push is what puts a refusal back. The surface changed, not the
  owner.
- **An application stack is atomic.** Every gesture that would change its count
  is refused — right-click split, drag-to-distribute, double-click gather,
  single-item throw — because the count is the window count and half a window is
  not a thing. Whole-stack moves are all allowed. Real items are untouched by
  all of it.
- **An application never lands on the ground.** `Q` in the world, `Q` and
  `Ctrl+Q` over a slot, and a click outside the inventory window with one on
  the cursor are all refused — it stays where it was, or on the cursor, and the
  way to unassign one is still to carry it up into storage. A dropped one was an
  item entity on a platform over a void and its slot unassigned as a side
  effect. Refused at the click (`AppClicks`, `ClientPlayerEntityMixin`), and
  backstopped on the integrated server at `ServerPlayerEntity.dropItem` — every
  vanilla drop route ends there, read out of the 1.21.1 bytecode, including
  closing a screen with a full inventory and death without `keepInventory` —
  where an application stack is simply not dropped.

## Visual state encoding (use vanilla MC rendering, don't invent UI)
Now literally vanilla's, rather than reproductions of it. Three of these four
stopped being our code in M8.
- **Enchantment glint** = app running — the real `ENCHANTMENT_GLINT_OVERRIDE`
  component, so it is the actual enchanted-item effect
- **Stack count** = number of open windows — a real stack size, drawn by vanilla
- **Hotbar selection highlight** = focused — the selection *follows* focus. It
  cannot also mean "what you are holding", and driving focus the other way would
  fire the pointer handshake on every notch of the scroll wheel and take focus
  out of Minecraft on the first one. Never blocks scrolling: it writes only when
  an application gains focus, when the keyboard is not Minecraft's anyway.
- **Dimmed / low opacity** = launching (spawned, window not yet mapped) — the one
  state with no vanilla component, carried on the stack so it is faded in the
  hand and the inventory too

## Click bindings
**On the item, in the world** (M8) — hold an application and click at the world.
This is the primary surface now; the overview's nine-slot row is gone, because
with real items it was a second hotbar drawn on top of the first one. Hooked at
`MinecraftClient`, not `Item.use`: right-clicking a block and right-clicking the
air take different routes into `Item` and only one of them is `use()`.

Left-click meaning *cycle* costs mining while an application is in hand, and
that is the trade: the world is a stone platform over a void. A pickaxe still
mines.

- Right-click → focus, or launch if not running
- Left-click → focus, cycle through that app's windows
- Shift+right-click → launch another one, running or not. The hotbar could
  otherwise only ever start an app's first window. Not a double-click:
  left-click already cycles, so a double-click would cycle once before it could
  mean anything else, and telling them apart would have to delay every click.
- Shift+middle-click → close window (Sway `close`, a polite request, not a kill)
- **Number keys only select a slot** (M8). They used to activate, back when the
  hotbar was drawn and a number could not mean anything else. Now the slot holds
  an item, `1` puts it in your hand, and the gesture that acts on it is the
  click that follows. A number key that both selected and launched would make
  reaching for an application indistinguishable from starting one.

A held right-click does *not* repeat. Vanilla stops that by setting a cooldown
after a use, and cancelling before that leaves nothing to set it — so the use
key must be released before it counts again, or shift+right-click held down is
twenty windows a second.
