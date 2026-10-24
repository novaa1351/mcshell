package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.ConfirmScreen;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;

/**
 * The machine's power state: lock, sleep, restart, power off.
 *
 * <p>Where <i>Save and Quit to Title</i> goes. There is no title screen in a
 * shell — the world is the desktop, and leaving it leaves a logged-in session
 * looking at nothing — so the button that meant "stop playing" is the one that
 * should mean "stop using the computer".
 *
 * <p>Four buttons at the pause menu's own width, in the pause menu's own
 * style, because that is the screen you came from and this is a continuation
 * of it rather than a new place.
 *
 * <p><b>The two that cannot be undone ask first.</b> Lock and Sleep are one
 * password away from where you were; Restart and Power Off close every window
 * on the machine, and they sit one button-height from the two that do not.
 * Vanilla's own confirmation screen asks, so the question looks like the game
 * asking it.
 *
 * <p>Nothing here decides anything. Each button is one message, and the daemon
 * does the deciding — as with the process kill button, what comes back is an
 * acceptance, not a result.
 */
public final class PowerScreen extends Screen {
	/** The pause menu's own button width, from {@code GameMenuScreen}. */
	private static final int BUTTON_W = 204;
	private static final int BUTTON_H = 20;
	private static final int GAP = 4;
	private static final int COUNT = 4;

	private final DaemonConnection connection;
	private final Screen parent;

	public PowerScreen(DaemonConnection connection, Screen parent) {
		super(Text.translatable("mcshell.power.title"));
		this.connection = connection;
		this.parent = parent;
	}

	@Override
	protected void init() {
		int x = width / 2 - BUTTON_W / 2;
		int y = height / 2 - (COUNT * BUTTON_H + (COUNT - 1) * GAP) / 2;

		add(x, y, "lock", () -> run("lock"));
		add(x, y + (BUTTON_H + GAP), "sleep", () -> run("sleep"));
		add(x, y + 2 * (BUTTON_H + GAP), "restart", () -> confirm("restart"));
		add(x, y + 3 * (BUTTON_H + GAP), "poweroff", () -> confirm("poweroff"));
	}

	private void add(int x, int y, String action, Runnable onPress) {
		addDrawableChild(ButtonWidget.builder(
						Text.translatable("mcshell.power." + action),
						button -> onPress.run())
				.dimensions(x, y, BUTTON_W, BUTTON_H).build());
	}

	/**
	 * Send it, and get out of the way.
	 *
	 * <p>Back to the world rather than back to the pause menu: the screen you
	 * unlock onto, or wake onto, should be the one you were using, not the
	 * menu you left through.
	 */
	private void run(String action) {
		connection.powerAction(action);
		if (client != null) {
			client.setScreen(null);
		}
	}

	private void confirm(String action) {
		if (client == null) {
			return;
		}
		client.setScreen(new ConfirmScreen(
				yes -> {
					if (yes) {
						run(action);
					} else {
						client.setScreen(this);
					}
				},
				Text.translatable("mcshell.power." + action),
				Text.translatable("mcshell.power.confirm." + action)));
	}

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		super.render(context, mouseX, mouseY, delta);
		int y = height / 2 - (COUNT * BUTTON_H + (COUNT - 1) * GAP) / 2;
		context.drawCenteredTextWithShadow(textRenderer, title, width / 2, y - 24, 0xFFFFFF);
	}

	@Override
	public void close() {
		// Back to the pause menu. There is no fifth button for it, because
		// there does not need to be — Escape is how every Minecraft screen is
		// left, and this one came from the screen Escape opens.
		if (client != null) {
			client.setScreen(parent);
		}
	}

	@Override
	public boolean shouldPause() {
		return false;
	}
}
