package dev.mcshell.screen;

import dev.mcshell.mixin.HandledScreenAccessor;
import dev.mcshell.net.DaemonConnection;
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents;
import net.fabricmc.fabric.api.client.screen.v1.Screens;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.ingame.InventoryScreen;
import net.minecraft.client.gui.tooltip.Tooltip;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.text.Text;
import net.minecraft.util.Identifier;

/**
 * What the survival inventory gains: a way into the catalog.
 *
 * <p>The shell is a survival world, so {@code E} still opens the real player
 * inventory. The catalog hangs off a tab on it, the way creative mode's pages
 * hang off each other — a real creative tab sprite with a chest on it, tucked
 * under the top-left edge of the panel at vanilla's own offsets. It was a
 * floating button off the panel's corner until M8, which looked exactly like
 * what it was: something added afterwards.
 *
 * <p>The work is split across two places and the split is deliberate. The
 * painting is in {@link dev.mcshell.mixin.InventoryScreenMixin}, because a tab
 * has to be drawn <em>before</em> the panel to tuck under it and no screen event
 * fires there. The clicking is a widget here, because a widget already knows how
 * to own a hit area, show a tooltip, play the click and narrate itself. So the
 * widget paints nothing and the mixin handles nothing.
 */
public final class InventoryIntegration {
	/** Vanilla's creative tab: 26x32, the item 5 across and 9 down. */
	private static final int TAB_W = 26;
	private static final int TAB_H = 32;
	private static final int TAB_RISE = 28;
	private static final int ICON_X = 5;
	private static final int ICON_Y = 9;

	/** Unselected, because the page you are looking at is the inventory. */
	private static final Identifier TAB_SPRITE =
			Identifier.ofVanilla("container/creative_inventory/tab_top_unselected_1");

	/** A chest, because that is what it opens: everything the machine has. */
	private static final ItemStack CHEST = new ItemStack(Items.CHEST);

	private InventoryIntegration() {
	}

	public static void register(DaemonConnection connection) {
		ScreenEvents.AFTER_INIT.register((client, screen, width, height) -> {
			if (!(screen instanceof InventoryScreen)) {
				return;
			}

			ButtonWidget open = new TabHitArea(button ->
					MinecraftClient.getInstance().setScreen(new CatalogScreen(connection)));
			open.setTooltip(Tooltip.of(Text.translatable("mcshell.catalog.open")));
			Screens.getButtons(screen).add(open);

			// Positioned every frame, not once here. Toggling the recipe book
			// slides the inventory panel sideways, and a tab placed at init
			// would be left behind on the old corner.
			ScreenEvents.beforeRender(screen).register((s, context, mouseX, mouseY, delta) -> {
				HandledScreenAccessor panel = (HandledScreenAccessor) s;
				open.setPosition(panel.mcshell$getX(), panel.mcshell$getY() - TAB_RISE);
			});
		});
	}

	/**
	 * Paint the tab. Called from the mixin, under the panel.
	 *
	 * <p>The item is pushed toward the viewer before it is drawn, exactly as
	 * {@code CreativeInventoryScreen} does: the panel is about to be painted
	 * over this same ground, and without the push it would swallow the chest.
	 */
	public static void drawCatalogTab(DrawContext context, InventoryScreen screen) {
		HandledScreenAccessor panel = (HandledScreenAccessor) screen;
		int tx = panel.mcshell$getX();
		int ty = panel.mcshell$getY() - TAB_RISE;

		context.drawGuiTexture(TAB_SPRITE, tx, ty, TAB_W, TAB_H);

		context.getMatrices().push();
		context.getMatrices().translate(0.0F, 0.0F, 100.0F);
		context.drawItem(CHEST, tx + ICON_X, ty + ICON_Y);
		context.getMatrices().pop();
	}

	/**
	 * The tab's hit area: a button that draws nothing.
	 *
	 * <p>Everything visible about this tab is painted under the panel, which a
	 * widget cannot reach. What is left is what a widget is genuinely good at,
	 * so the rendering is simply omitted rather than replaced.
	 */
	private static final class TabHitArea extends ButtonWidget {
		private TabHitArea(PressAction onPress) {
			super(0, 0, TAB_W, TAB_H, Text.empty(), onPress, DEFAULT_NARRATION_SUPPLIER);
		}

		@Override
		public void renderWidget(DrawContext context, int mouseX, int mouseY, float delta) {
			// Painted by InventoryScreenMixin, behind the panel.
		}
	}
}
