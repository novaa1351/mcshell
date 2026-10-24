package dev.mcshell.item;

import dev.mcshell.MCShellClient;
import net.minecraft.item.Item;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.util.Identifier;

/**
 * Registration for the single application item.
 *
 * <p>Called from the client entrypoint, which is late enough to look alarming
 * and is not. Vanilla freezes its registries in {@code Bootstrap.initialize},
 * before {@code MinecraftClient}'s constructor ever runs — but Fabric API's
 * {@code BootstrapMixin} redirects {@code Registries.bootstrap()} to
 * {@code Registries.init()}, dropping the freeze from that path entirely, so
 * registration from a mod entrypoint is exactly what it looks like. Measured
 * against the loader and mapping files rather than assumed; fabric-api is a hard
 * dependency in fabric.mod.json, so it is always there to do it.
 *
 * <p>No recipe, no use, no fuel value, no item group: this exists to be looked
 * at and clicked on. The click interceptor is what makes it inert in the ways a
 * plain {@code Item} is not.
 */
public final class AppItems {
	public static final Identifier APP_ID = Identifier.of(MCShellClient.MOD_ID, "app");

	/** Assigned once by {@link #register()}, before anything can draw a stack. */
	public static Item APP;

	private AppItems() {
	}

	public static void register() {
		if (APP != null) {
			return;
		}
		APP = Registry.register(Registries.ITEM, APP_ID, new AppItem(new Item.Settings()));
	}
}
