package dev.mcshell.item;

import net.minecraft.item.ItemStack;
import net.minecraft.screen.ScreenHandler;
import net.minecraft.screen.slot.SlotActionType;

/**
 * The one rule that makes an application stack behave like an application.
 *
 * <p><b>An application stack is atomic.</b> Anything that would move it as a
 * whole is ordinary inventory handling and is left alone — picking it up,
 * dropping it somewhere else, shift-clicking it into storage, swapping it with
 * a number key. Anything that would change its <em>count</em> is refused.
 *
 * <p>That rule exists because the count is not a quantity. A stack of three
 * Braves is three open windows, so splitting it in half is a request for one and
 * a half windows — there is no arrangement of items that could answer it, and
 * the reconcile on the next taskbar push would undo it within a tick anyway.
 * Refusing outright is the honest version of what would happen regardless.
 *
 * <p><b>And an application never lands on the ground.</b> A dropped one is an
 * item entity on a platform over a void, gone in five minutes, and its slot
 * unassigned as a side effect nobody asked for. Q in the world was refused from
 * the start; dragging one out of the window and Ctrl+Q over a slot are the same
 * act by other routes, and are refused here. The integrated server refuses it
 * too, as a backstop: see {@code ServerPlayerEntityMixin}.
 *
 * <p>Real Minecraft items are never touched by any of this. Wood splits, stacks
 * and drops exactly as it always did.
 */
public final class AppClicks {
	private AppClicks() {
	}

	/**
	 * Whether this click should be refused outright.
	 *
	 * @param slotId the screen handler's slot index, or negative for a click
	 *               outside the window
	 */
	public static boolean refuse(ScreenHandler handler, int slotId, int button,
			SlotActionType actionType) {

		ItemStack cursor = handler.getCursorStack();
		ItemStack target = slotId >= 0 && slotId < handler.slots.size()
				? handler.getSlot(slotId).getStack()
				: ItemStack.EMPTY;

		if (!AppItem.is(cursor) && !AppItem.is(target)) {
			return false;
		}

		return switch (actionType) {
			// Outside the window, either button throws what the cursor holds:
			// the left one all of it, the right one a single item. On a slot,
			// the right button is the splitting button — it takes half, or
			// places one — and every use of it changes a count.
			case PICKUP -> slotId == ScreenHandler.EMPTY_SPACE_SLOT_INDEX
					? AppItem.is(cursor)
					: button == 1;
			// Q over a slot: 0 throws one item, 1 (Ctrl+Q) the whole stack.
			// Both put an application on the ground.
			case THROW -> true;
			// Drag-to-distribute and double-click-to-gather are both defined as
			// moving part of a stack.
			case QUICK_CRAFT, PICKUP_ALL -> true;
			// PICKUP with the left button, QUICK_MOVE, SWAP: whole stacks, and
			// all three are legitimate ways to rearrange the hotbar.
			default -> false;
		};
	}
}
