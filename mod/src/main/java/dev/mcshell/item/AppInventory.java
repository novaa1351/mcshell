package dev.mcshell.item;

import dev.mcshell.MCShellClient;
import dev.mcshell.net.DaemonConnection;
import dev.mcshell.net.TaskbarState;
import net.minecraft.client.MinecraftClient;
import net.minecraft.entity.player.PlayerInventory;
import net.minecraft.item.ItemStack;
import net.minecraft.server.integrated.IntegratedServer;
import net.minecraft.server.network.ServerPlayerEntity;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.Objects;
import java.util.UUID;

/**
 * Keeps the player's hotbar holding the applications the daemon describes.
 *
 * <p>This is the whole of the "items follow the overlay" behaviour, and it is
 * deliberately one-way. Stacks are <em>derived</em> from every {@code taskbar}
 * message and never read back as truth: the daemon still decides what is
 * assigned where, and a click that would move an application is forwarded to it
 * rather than applied here. The surface the state is drawn on changed; who owns
 * the state did not.
 *
 * <p>Written through the <em>integrated server</em>, not the client's own copy
 * of the inventory. The client copy is a mirror the server overwrites whenever
 * it revalidates a slot, so client-side stacks survive until the first real
 * inventory event and then silently vanish — which is the classic version of
 * this bug. The world here is always singleplayer, so the server is in the same
 * JVM and vanilla syncs the change back down for free; in multiplayer there is
 * no server to reach and this does nothing at all.
 */
public final class AppInventory {
	/** Nine assignable slots, matching the number keys. */
	private static final int HOTBAR = 9;

	private final DaemonConnection connection;

	/**
	 * The snapshot last written, compared by identity.
	 *
	 * <p>Identity is enough: the connection publishes a fresh
	 * {@link TaskbarState} per message, and the daemon already suppresses
	 * byte-identical repeats, so this settles to one reconcile per real change.
	 */
	private TaskbarState applied;

	/**
	 * Slot (0-based) to desktop id, as of the last arrangement we wrote or saw.
	 *
	 * <p>This is what makes a drag mean something. Nothing hooks the click that
	 * moves an application: the click is allowed to happen exactly as it would
	 * for any item, and afterwards the hotbar simply no longer matches what was
	 * written, which is reported to the daemon as the new arrangement. Every way
	 * of moving a stack — dragging, shift-clicking, a number key — is therefore
	 * handled by not handling any of them.
	 */
	private Map<Integer, String> written = Map.of();

	/**
	 * Whether the inventory has caught up with the last write.
	 *
	 * <p>The write goes through the server thread, so for a tick or two the
	 * inventory legitimately disagrees with {@link #written}. Without this the
	 * reconciler's own writes would read as the player rearranging things, and
	 * every taskbar push would bounce straight back at the daemon.
	 */
	private boolean settled = true;

	/** The slot whose application last held the compositor's focus, or -1. */
	private int focused = -1;

	/**
	 * Hotbar slots holding an ordinary Minecraft item, as last reported.
	 *
	 * <p>Null until the first report, so an empty hotbar is still sent once
	 * rather than mistaken for "nothing to say".
	 */
	private Set<Integer> occupied;

	/** So a daemon that restarted is told about the player's wood again. */
	private boolean wasConnected;

	public AppInventory(DaemonConnection connection) {
		this.connection = connection;
	}

	public void tick(MinecraftClient client) {
		if (client.player == null) {
			// Between worlds. Forgetting what was written means the next join
			// reconciles against whatever the save had in it, which is the only
			// moment stale application items from a previous session can appear.
			applied = null;
			written = Map.of();
			settled = true;
			occupied = null;
			return;
		}

		IntegratedServer server = client.getServer();
		if (server == null) {
			return;
		}

		// A reconnected daemon has forgotten everything the mod told it, and
		// occupancy is only ever sent on a change — so without this it would
		// never hear about a slot that has not moved since.
		boolean connected = connection.connected();
		if (connected && !wasConnected) {
			occupied = null;
		}
		wasConnected = connected;

		TaskbarState state = connection.state();
		if (state != applied) {
			applied = state;
			followFocus(client, state);
			written = arrangementOf(state);
			settled = false;

			UUID uuid = client.player.getUuid();
			server.execute(() -> apply(server, uuid, state));
			return;
		}

		Map<Integer, String> actual = observe(client.player.getInventory());
		if (!settled) {
			settled = actual.equals(written);
			return;
		}

		Set<Integer> holding = occupiedSlots(client.player.getInventory());
		if (!holding.equals(occupied)) {
			connection.slotsOccupied(holding);
			occupied = holding;
		}

		if (!actual.equals(written)) {
			// The player moved something. Report it and stop repeating; the
			// daemon answers with a taskbar, which reconciles as usual — and if
			// it refuses part of the arrangement, that push is what puts it
			// back.
			connection.slotsArrange(actual);
			written = actual;
		}
	}

	/**
	 * Hold the application that has the screen.
	 *
	 * <p>CLAUDE.md encodes "focused" as the hotbar selection highlight, and with
	 * real items that highlight belongs to whatever the player is holding — it
	 * cannot mean two things. So the selection follows focus instead: when an
	 * application takes the compositor's focus, it is what you are holding.
	 *
	 * <p>Deliberately this way round rather than the reverse. Driving focus
	 * <em>from</em> the selection would put a window focus change on every notch
	 * of the scroll wheel, and each one runs the pointer handshake — the game is
	 * asked for the mouse and the daemon waits up to 250ms for the
	 * acknowledgement. Worse, the first one would succeed: focus would leave
	 * Minecraft, and the scroll wheel with it. Focusing an application stays
	 * with the number keys and right-click, which already do the handshake in
	 * the right order.
	 *
	 * <p>It follows that this can never fight the player for the slot. It writes
	 * only when an application <em>gains</em> focus, and at that moment the
	 * keyboard belongs to that application rather than to Minecraft. Playing the
	 * game with an application merely open leaves the selection alone entirely.
	 */
	private void followFocus(MinecraftClient client, TaskbarState state) {
		int now = -1;
		for (int i = 0; i < HOTBAR; i++) {
			TaskbarState.Slot slot = state.at(i);
			if (slot != null && slot.assigned() && slot.focused()) {
				now = i;
				break;
			}
		}

		// Only on the change, and only towards an application. Focus returning
		// to Minecraft leaves the player holding whatever they were holding.
		if (now >= 0 && now != focused) {
			client.player.getInventory().selectedSlot = now;
		}
		focused = now;
	}

	/**
	 * Hotbar slots holding something that is not an application.
	 *
	 * <p>The daemon uses this to leave the player's things alone: a slot with
	 * wood in it is a worse home for a running application than an empty one,
	 * and it is the only side that can see the difference.
	 */
	private static Set<Integer> occupiedSlots(PlayerInventory inventory) {
		Set<Integer> slots = new HashSet<>();
		for (int i = 0; i < HOTBAR; i++) {
			ItemStack stack = inventory.getStack(i);
			if (!stack.isEmpty() && !AppItem.is(stack)) {
				slots.add(i);
			}
		}
		return slots;
	}

	/** What the daemon says the hotbar holds. */
	private static Map<Integer, String> arrangementOf(TaskbarState state) {
		Map<Integer, String> apps = new HashMap<>();
		for (int i = 0; i < HOTBAR; i++) {
			TaskbarState.Slot slot = state.at(i);
			if (slot != null && slot.assigned()) {
				apps.put(i, slot.app());
			}
		}
		return apps;
	}

	/**
	 * What the hotbar actually holds.
	 *
	 * <p>Only the nine. An application carried up into storage is simply absent
	 * from here, which is what unassigns its slot; the sweep in
	 * {@link #apply} takes the item itself on the next push.
	 */
	private static Map<Integer, String> observe(PlayerInventory inventory) {
		Map<Integer, String> apps = new HashMap<>();
		for (int i = 0; i < HOTBAR; i++) {
			ItemStack stack = inventory.getStack(i);
			if (AppItem.is(stack)) {
				apps.put(i, AppItem.appId(stack));
			}
		}
		return apps;
	}

	/** On the server thread: make the inventory say what the daemon said. */
	private static void apply(IntegratedServer server, UUID uuid, TaskbarState state) {
		ServerPlayerEntity player = server.getPlayerManager().getPlayer(uuid);
		if (player == null) {
			return;
		}
		PlayerInventory inventory = player.getInventory();

		ItemStack[] desired = new ItemStack[HOTBAR];
		for (int i = 0; i < HOTBAR; i++) {
			TaskbarState.Slot slot = state.at(i);
			if (slot != null && slot.assigned()) {
				desired[i] = AppItem.stack(
						slot.app(), slot.iconPath(), slot.displayName(),
						slot.windows(), slot.running(), slot.launching());
			}
		}

		// Sweep first, place second. An application item anywhere it is no
		// longer wanted goes, including one that has been carried up into the
		// 27 — dragging an application out of the hotbar unassigns the slot, so
		// there is nothing left for the item to mean up there.
		for (int i = 0; i < PlayerInventory.MAIN_SIZE; i++) {
			ItemStack stack = inventory.getStack(i);
			if (!AppItem.is(stack)) {
				continue;
			}
			boolean wanted = i < HOTBAR && desired[i] != null
					&& Objects.equals(AppItem.appId(stack), AppItem.appId(desired[i]));
			if (!wanted) {
				inventory.setStack(i, ItemStack.EMPTY);
			}
		}

		for (int i = 0; i < HOTBAR; i++) {
			if (desired[i] == null) {
				continue;
			}
			ItemStack current = inventory.getStack(i);
			if (AppItem.is(current)) {
				// The same application — the sweep took every other. Rewrite it
				// only if something it shows has actually moved: the window
				// count, the name, or an icon that has appeared since.
				if (!ItemStack.areEqual(current, desired[i])) {
					inventory.setStack(i, desired[i]);
				}
				continue;
			}
			if (!current.isEmpty()) {
				displace(player, inventory, i, current);
			}
			inventory.setStack(i, desired[i]);
		}
	}

	/**
	 * Move a real Minecraft item out of a slot an application needs.
	 *
	 * <p>Rare by construction: an application item makes its slot non-empty and
	 * never stacks with anything else, so vanilla's pickup search will not put
	 * wood there in the first place. This is for the case where the assignment
	 * arrives after the wood did.
	 *
	 * <p>Storage first, and only then the floor. Dropping is close to
	 * destruction in this world — the Void preset has a small platform and
	 * nothing else, and an item lying on it despawns in five minutes — so it is
	 * what happens when all 36 slots are genuinely full, not a first resort.
	 */
	private static void displace(ServerPlayerEntity player, PlayerInventory inventory,
			int from, ItemStack stack) {
		for (int i = HOTBAR; i < PlayerInventory.MAIN_SIZE; i++) {
			if (inventory.getStack(i).isEmpty()) {
				inventory.setStack(i, stack);
				inventory.setStack(from, ItemStack.EMPTY);
				return;
			}
		}

		inventory.setStack(from, ItemStack.EMPTY);
		player.dropItem(stack, false);
		MCShellClient.LOG.info("inventory full; dropped {} to free hotbar slot {}",
				stack.getItem(), from + 1);
	}
}
