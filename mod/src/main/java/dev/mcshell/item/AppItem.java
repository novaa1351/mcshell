package dev.mcshell.item;

import net.minecraft.component.DataComponentTypes;
import net.minecraft.component.type.NbtComponent;
import net.minecraft.item.Item;
import net.minecraft.item.ItemStack;
import net.minecraft.nbt.NbtCompound;
import net.minecraft.text.Text;
import org.jetbrains.annotations.Nullable;

/**
 * The one item every application is made of.
 *
 * <p>There is exactly one registered item, {@code mcshell:app}, and which
 * application a stack of it <em>is</em> lives in a component. That is not a
 * shortcut: registries freeze during startup and the catalog is discovered from
 * the daemon at runtime, so an item per {@code .desktop} file could never be
 * registered. Nothing about this is visible in game — each stack carries its own
 * name and its own icon.
 *
 * <p>The data rides in vanilla's {@code custom_data}, which is the sanctioned
 * place for a mod to hang NBT on a stack and needs no component type of its own.
 * It earns its keep twice over: {@code PlayerInventory}'s pickup search compares
 * items <em>and components</em>, so two different applications never merge into
 * one stack, and wood never merges into either.
 *
 * <p>The icon path is stored beside the desktop id rather than looked up in the
 * taskbar state at draw time. A stack is then self-describing, which keeps the
 * renderer off the shared state on the hot path and lets a stack that briefly
 * outlives its slot still draw as itself.
 *
 * <p><b>This is still a rendering of daemon state.</b> Stacks are re-derived
 * from every {@code taskbar} message and clicks are forwarded rather than
 * applied, so the daemon remains the only thing that decides anything. What
 * changed in M8 is the surface the state is drawn on, not who owns it.
 */
public final class AppItem extends Item {
	/** Namespaced inside custom_data, because that compound is shared ground. */
	private static final String APP = "mcshell_app";
	private static final String ICON = "mcshell_icon";
	private static final String LAUNCHING = "mcshell_launching";

	public AppItem(Settings settings) {
		super(settings);
	}

	/**
	 * Build the stack for one hotbar slot.
	 *
	 * @param count   window count — a stack of three is three open windows,
	 *                which is the vanilla encoding CLAUDE.md asks for, now drawn
	 *                by vanilla itself rather than by hand
	 * @param running whether the application has a window open, shown as the
	 *                enchantment glint. Also vanilla's own: the glint override
	 *                is a real component, so this is the actual enchanted-item
	 *                effect rather than a sheen drawn to resemble one.
	 * @param launching spawned, with no window mapped yet. Drawn faded.
	 */
	public static ItemStack stack(String appId, @Nullable String iconPath, String name,
			int count, boolean running, boolean launching) {
		ItemStack stack = new ItemStack(AppItems.APP, Math.max(1, count));

		NbtCompound nbt = new NbtCompound();
		nbt.putString(APP, appId);
		if (iconPath != null && !iconPath.isEmpty()) {
			nbt.putString(ICON, iconPath);
		}
		// On the stack rather than drawn over the slot afterwards, so a
		// launching application is faded everywhere it appears — the hotbar,
		// the inventory, and the hand — from one place. The visual encoding is
		// the language of this interface, and a second copy of it drifts.
		if (launching) {
			nbt.putBoolean(LAUNCHING, true);
		}
		NbtComponent.set(DataComponentTypes.CUSTOM_DATA, stack, nbt);

		// Not italic. Vanilla slants a custom name to mean "somebody renamed
		// this", and Firefox is not a renamed anything — that is its name.
		stack.set(DataComponentTypes.CUSTOM_NAME,
				Text.literal(name).styled(style -> style.withItalic(false)));

		if (running) {
			stack.set(DataComponentTypes.ENCHANTMENT_GLINT_OVERRIDE, true);
		}
		return stack;
	}

	/**
	 * Whether this stack is an application.
	 *
	 * <p>Asked for every stack the game draws, several times a frame, so it
	 * deliberately stops at {@code contains} rather than reading a value out —
	 * the only non-deprecated way to read the compound copies it, and copying
	 * one per item per frame to answer a yes-or-no question is waste.
	 */
	public static boolean is(ItemStack stack) {
		if (stack.isEmpty() || !(stack.getItem() instanceof AppItem)) {
			return false;
		}
		NbtComponent data = stack.get(DataComponentTypes.CUSTOM_DATA);
		return data != null && data.contains(APP);
	}

	/** The desktop id this stack stands for, or null if it is not an app item. */
	@Nullable
	public static String appId(ItemStack stack) {
		return read(stack, APP);
	}

	/** Absolute path to the application's icon, or null when it has none. */
	@Nullable
	public static String iconPath(ItemStack stack) {
		return read(stack, ICON);
	}

	/** {@code copyNbt} rather than {@code getNbt}: the latter is deprecated for
	 * handing out the component's own mutable compound. */
	/** Spawned, no window yet. */
	public static boolean isLaunching(ItemStack stack) {
		NbtComponent data = stack.get(DataComponentTypes.CUSTOM_DATA);
		return data != null && data.contains(LAUNCHING);
	}

	@Nullable
	private static String read(ItemStack stack, String key) {
		NbtComponent data = stack.get(DataComponentTypes.CUSTOM_DATA);
		if (data == null || !data.contains(key)) {
			return null;
		}
		String value = data.copyNbt().getString(key);
		return value.isEmpty() ? null : value;
	}
}
