package dev.mcshell.item;

import dev.mcshell.MCShellClient;
import net.minecraft.client.MinecraftClient;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.entity.player.PlayerInventory;

/**
 * What an application does when you use it, holding it, in the world.
 *
 * <p>The hotbar slots are real items, so the obvious thing to do with one is the
 * thing you do with every other item: point at the world and click. These are
 * the same four bindings the overview had, moved onto the item itself —
 *
 * <ul>
 *   <li>right-click — focus, or launch if it is not running
 *   <li>shift+right-click — launch another window, running or not
 *   <li>left-click — focus, then cycle that application's windows
 *   <li>shift+middle-click — close a window, politely
 * </ul>
 *
 * <p>Which is why left-click no longer mines while an application is in hand.
 * The two want the same button, and the alternative is worse than losing the
 * pick: the world is a small stone platform over a void, and mining it out from
 * under yourself with Brave in hand is not a recoverable afternoon.
 *
 * <p>Nothing is decided here. Each gesture is a {@code slot_activate} or a
 * {@code slot_close} and the daemon works out what it means, exactly as it does
 * for a click in the overview.
 */
public final class AppGestures {
	/**
	 * Whether the use key has already fired since it was last released.
	 *
	 * <p>Vanilla stops a held right-click from repeating by setting a four-tick
	 * cooldown after a use, and cancelling before that leaves nothing to set it
	 * — so a held button would activate twenty times a second, which for
	 * shift+right-click means twenty windows. Reset from the client tick when
	 * the key comes up, so a launch takes a press rather than a duration.
	 */
	private static boolean useConsumed;

	private AppGestures() {
	}

	/** Let go of the use key: the next press counts again. */
	public static void tick(MinecraftClient client) {
		if (useConsumed && !client.options.useKey.isPressed()) {
			useConsumed = false;
		}
	}

	/** The hotbar slot of the application in the player's hand, or -1. */
	public static int heldSlot(PlayerEntity player) {
		if (player == null) {
			return -1;
		}
		PlayerInventory inventory = player.getInventory();
		int selected = inventory.selectedSlot;
		if (!PlayerInventory.isValidHotbarIndex(selected)) {
			return -1;
		}
		return AppItem.is(inventory.getStack(selected)) ? selected : -1;
	}

	public static boolean holdingApp(PlayerEntity player) {
		return heldSlot(player) >= 0;
	}

	/**
	 * Right-click. Returns whether the gesture belonged to us, which is not the
	 * same as whether anything was sent — a held button belongs to us and is
	 * deliberately ignored, and letting it through instead would swing the arm
	 * at the world every tick.
	 */
	public static boolean use(PlayerEntity player, boolean sneaking) {
		int slot = heldSlot(player);
		if (slot < 0) {
			return false;
		}
		if (!useConsumed) {
			useConsumed = true;
			MCShellClient.connection().slotActivate(slot + 1, sneaking ? "shift_right" : "right");
		}
		return true;
	}

	/** Left-click: focus and cycle. Fired once per press by the caller. */
	public static boolean attack(PlayerEntity player) {
		int slot = heldSlot(player);
		if (slot < 0) {
			return false;
		}
		MCShellClient.connection().slotActivate(slot + 1, "left");
		return true;
	}

	/** Shift+middle-click: ask Sway to close a window. Not a kill. */
	public static boolean close(PlayerEntity player, boolean sneaking) {
		int slot = heldSlot(player);
		if (slot < 0 || !sneaking) {
			return false;
		}
		MCShellClient.connection().slotClose(slot + 1);
		return true;
	}
}
