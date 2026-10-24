package dev.mcshell.screen;

import dev.mcshell.item.AppItem;
import dev.mcshell.net.CatalogState;
import dev.mcshell.net.DaemonConnection;
import dev.mcshell.net.TaskbarState;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.ingame.HandledScreen;
import net.minecraft.client.gui.widget.TextFieldWidget;
import net.minecraft.item.ItemStack;
import net.minecraft.item.Items;
import net.minecraft.text.Text;
import net.minecraft.util.Identifier;
import net.minecraft.util.math.MathHelper;
import org.lwjgl.glfw.GLFW;

import java.util.ArrayList;
import java.util.List;

/**
 * The catalog: every application on the machine, laid out as the creative
 * inventory.
 *
 * <p>Reached from the chest tab on the survival inventory, the way creative mode
 * reaches its item list. Assignment is the creative gesture — click an app to
 * pick it up, click a slot to put it down. Not an HTML5-style drag: you are not
 * holding the button down, and the held app follows the cursor across tab
 * changes and scrolling.
 *
 * <p>The chrome is <b>vanilla's own</b> (M8), down to the pixel: the creative
 * panel texture, the creative tab sprites, the creative slot highlight, and the
 * geometry copied from {@code CreativeInventoryScreen} rather than approximated
 * — 9x5 slots at {@code (9 + col*18, 18 + row*18)}, the hotbar at {@code y+112},
 * the scrollbar at {@code x+175}, the search field at {@code (x+82, y+6)}. It
 * previously drew its own dark panel, which was tidy and looked like a different
 * game. CLAUDE.md's rule is to use vanilla rendering rather than invent UI, and
 * a screen that sits beside the real inventory is where that shows most.
 *
 * <p>The tabs carry items rather than words for the same reason. Minecraft has
 * never labelled a creative tab in text, and "Games / Web / Work" in a row of
 * boxes reads as a web app embedded in a game.
 *
 * <p>It renders what the daemon last sent and forwards clicks. It does not know
 * which apps exist, what a tab means, or whether an assignment succeeded — the
 * daemon answers a {@code slot_assign} with a fresh taskbar, and the row at the
 * bottom shows the result on the way back.
 */
public final class CatalogScreen extends Screen {
	/**
	 * A tab: the id the daemon knows it by, the lang key, and the item on it.
	 *
	 * <p>The icons are chosen to be guessable before they are learned, using
	 * whatever Minecraft already means by them: a sword is what the game calls
	 * combat, redstone is what it calls machinery, a compass is what it gives
	 * you for finding your way. Changing one is a line here.
	 */
	private record Tab(String id, String key, ItemStack icon) {
	}

	/**
	 * The daemon's six tabs, plus Search — seven, which is exactly the number of
	 * tabs vanilla fits in a row. The sprites come in seven shapes and the
	 * seventh is the one with the closed right edge, so the row ends correctly
	 * for free.
	 *
	 * <p>Search is not a category and is not sent as one: it queries across
	 * every tab, so its {@code id} is null.
	 */
	private static final List<Tab> TABS = List.of(
			new Tab("Games", "games", new ItemStack(Items.DIAMOND_SWORD)),
			new Tab("Browsing", "browsing", new ItemStack(Items.COMPASS)),
			new Tab("Productivity", "productivity", new ItemStack(Items.CRAFTING_TABLE)),
			new Tab("Media", "media", new ItemStack(Items.JUKEBOX)),
			new Tab("Tech", "tech", new ItemStack(Items.REDSTONE)),
			new Tab("Misc", "misc", new ItemStack(Items.BARREL)),
			// A spyglass rather than vanilla's compass, which is already the
			// browsing tab here. Looking for something, versus finding your way.
			new Tab(null, "search", new ItemStack(Items.SPYGLASS)));

	private static final int SEARCH_TAB = TABS.size() - 1;

	// -- vanilla creative geometry, copied rather than approximated ---------
	private static final int BG_W = 195;
	private static final int BG_H = 136;
	private static final int COLS = 9;
	private static final int ROWS = 5;
	private static final int SLOT = 18;
	private static final int GRID_X = 9;
	private static final int GRID_Y = 18;
	private static final int HOTBAR_Y = 112;
	private static final int TAB_W = 26;
	private static final int TAB_H = 32;
	private static final int TAB_PITCH = 27;
	private static final int SCROLLER_X = 175;
	private static final int SCROLLER_W = 12;
	private static final int SCROLLER_H = 15;
	/** The scrollbar's track: 112 tall, and 14 wide to grab, not the sprite's 12. */
	private static final int SCROLLER_TRACK = 112;
	private static final int SCROLLER_GRAB_W = 14;
	/** Vanilla's dark label grey. Not white: this texture is a light panel. */
	private static final int LABEL = 4210752;

	private static final Identifier BACKGROUND =
			Identifier.ofVanilla("textures/gui/container/creative_inventory/tab_items.png");
	private static final Identifier BACKGROUND_SEARCH =
			Identifier.ofVanilla("textures/gui/container/creative_inventory/tab_item_search.png");
	private static final Identifier SCROLLER =
			Identifier.ofVanilla("container/creative_inventory/scroller");
	private static final Identifier SCROLLER_DISABLED =
			Identifier.ofVanilla("container/creative_inventory/scroller_disabled");

	private static final Identifier[] TAB_SELECTED = tabSprites("selected");
	private static final Identifier[] TAB_UNSELECTED = tabSprites("unselected");

	private static Identifier[] tabSprites(String state) {
		Identifier[] out = new Identifier[7];
		for (int i = 0; i < out.length; i++) {
			out[i] = Identifier.ofVanilla(
					"container/creative_inventory/tab_top_" + state + "_" + (i + 1));
		}
		return out;
	}

	private final DaemonConnection connection;

	/** Panel origin, vanilla's `this.x` and `this.y`. */
	private int x;
	private int y;

	private TextFieldWidget search;

	private int tab;
	private int scrollRow;
	/**
	 * Whether the scrollbar is being dragged.
	 *
	 * <p>Held across frames rather than derived from the cursor, because vanilla
	 * does: once you have the scroller you keep it until the button comes up,
	 * even if the pointer wanders off the track. Letting go the moment the mouse
	 * left the 14px column would make the bar feel like it was slipping.
	 */
	private boolean scrolling;

	/**
	 * The catalog as item stacks, rebuilt when the daemon sends a new page.
	 *
	 * <p>Applications are drawn as real {@code mcshell:app} stacks, the same as
	 * everywhere else, so vanilla draws them and the icons match the hotbar
	 * exactly. Cached because building nine rows of stacks every frame to draw
	 * forty-five of them would be silly; the catalog is a fresh object per
	 * message, so identity is enough to notice a change.
	 */
	private CatalogState stacksFor;
	private List<ItemStack> stacks = List.of();

	/** The app on the cursor, or null. */
	private CatalogState.Item held;
	/**
	 * Which slot the held app came from, or 0 if it came from the catalog.
	 *
	 * <p>The source slot is not cleared when the app is picked up, only once it
	 * has landed somewhere else or been dropped outside the panel. Closing the
	 * screen mid-carry therefore changes nothing, which is the behaviour that
	 * does not lose an assignment to a mis-pressed Escape.
	 */
	private int heldFrom;

	public CatalogScreen(DaemonConnection connection) {
		super(Text.translatable("mcshell.catalog.title"));
		this.connection = connection;
	}

	// -- layout ------------------------------------------------------------

	@Override
	protected void init() {
		x = (width - BG_W) / 2;
		y = (height - BG_H) / 2;

		// Vanilla's search field, in vanilla's place: no background of its own,
		// because the search texture draws the well it sits in.
		search = new TextFieldWidget(textRenderer, x + 82, y + 6, 80, 9,
				Text.translatable("mcshell.catalog.search"));
		search.setMaxLength(50);
		search.setDrawsBackground(false);
		search.setEditableColor(0xFFFFFF);
		search.setChangedListener(text -> {
			scrollRow = 0;
			query();
		});
		addSelectableChild(search);
		syncSearchVisibility();

		query();
	}

	/** The search box exists only on the Search tab; elsewhere the header is a title. */
	private void syncSearchVisibility() {
		boolean on = tab == SEARCH_TAB;
		search.setVisible(on);
		search.setFocusUnlocked(!on);
		setFocused(on ? search : null);
		search.setFocused(on);
	}

	private void query() {
		Tab t = TABS.get(tab);
		connection.catalogQuery(t.id() == null ? search.getText() : "", t.id());
	}

	/**
	 * A shell must not stop the world behind it — and here the world behind it
	 * is the desktop.
	 */
	@Override
	public boolean shouldPause() {
		return false;
	}

	// -- rendering ---------------------------------------------------------

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		super.render(context, mouseX, mouseY, delta);

		List<ItemStack> items = catalogStacks();

		// Unselected tabs first, so the panel covers the edge they tuck under.
		for (int i = 0; i < TABS.size(); i++) {
			if (i != tab) {
				drawTab(context, i);
			}
		}

		context.drawTexture(tab == SEARCH_TAB ? BACKGROUND_SEARCH : BACKGROUND,
				x, y, 0, 0, BG_W, BG_H);

		if (tab == SEARCH_TAB) {
			search.render(context, mouseX, mouseY, delta);
		}
		drawScroller(context, items.size());

		// And the selected tab last, drawn over the panel edge so it reads as
		// joined to it. This is the whole reason vanilla splits the two loops.
		drawTab(context, tab);

		// A dead daemon looks exactly like a machine with no applications
		// installed, so say which it is.
		if (!connection.connected()) {
			context.drawText(textRenderer, Text.translatable("mcshell.overview.disconnected"),
					x + 8, y + 6, 0xFF5555, false);
		} else if (tab != SEARCH_TAB) {
			context.drawText(textRenderer, tabName(tab), x + 8, y + 6, LABEL, false);
		}

		drawGrid(context, items, mouseX, mouseY);
		drawHotbar(context, mouseX, mouseY);

		// Above everything, including the tooltip that would otherwise cover it.
		if (held != null) {
			drawHeld(context, mouseX, mouseY);
		} else {
			drawHover(context, mouseX, mouseY);
		}
	}

	private Text tabName(int index) {
		return Text.translatable("mcshell.catalog.tab." + TABS.get(index).key());
	}

	/** One tab, at vanilla's offsets, with its item sitting on it. */
	private void drawTab(DrawContext context, int index) {
		Identifier[] sprites = index == tab ? TAB_SELECTED : TAB_UNSELECTED;
		int tx = x + TAB_PITCH * index;
		int ty = y - 28;

		context.drawGuiTexture(sprites[MathHelper.clamp(index, 0, sprites.length - 1)],
				tx, ty, TAB_W, TAB_H);

		// Pushed toward the viewer so the item is not swallowed by the panel
		// drawn afterwards, exactly as vanilla does it.
		context.getMatrices().push();
		context.getMatrices().translate(0.0F, 0.0F, 100.0F);
		context.drawItem(TABS.get(index).icon(), tx + 5, ty + 9);
		context.getMatrices().pop();
	}

	private void drawScroller(DrawContext context, int total) {
		int totalRows = (total + COLS - 1) / COLS;
		boolean live = totalRows > ROWS;
		int maxScroll = Math.max(0, totalRows - ROWS);
		int offset = maxScroll == 0 ? 0
				: (SCROLLER_TRACK - SCROLLER_H - 2) * scrollRow / maxScroll;
		context.drawGuiTexture(live ? SCROLLER : SCROLLER_DISABLED,
				x + SCROLLER_X, y + GRID_Y + offset, SCROLLER_W, SCROLLER_H);
	}

	private void drawGrid(DrawContext context, List<ItemStack> items, int mouseX, int mouseY) {
		int first = scrollRow * COLS;
		for (int cell = 0; cell < ROWS * COLS; cell++) {
			int index = first + cell;
			int sx = x + GRID_X + (cell % COLS) * SLOT;
			int sy = y + GRID_Y + (cell / COLS) * SLOT;

			if (index < items.size()) {
				ItemStack stack = items.get(index);
				context.drawItem(stack, sx, sy);
				context.drawItemInSlot(textRenderer, stack, sx, sy);
			}
			if (inSlot(mouseX, mouseY, sx, sy)) {
				HandledScreen.drawSlotHighlight(context, sx, sy, 0);
			}
		}
	}

	/**
	 * The player's real hotbar, along the bottom, as the creative screen shows
	 * it.
	 *
	 * <p>Read from the inventory rather than from the taskbar: the slots hold
	 * real items now, so this is the same nine stacks the HUD is drawing, wood
	 * included. Clicking one is still an assignment — the row is a view of the
	 * hotbar, and what a click on it means is the daemon's business.
	 */
	private void drawHotbar(DrawContext context, int mouseX, int mouseY) {
		if (client == null || client.player == null) {
			return;
		}
		for (int i = 0; i < COLS; i++) {
			int sx = x + GRID_X + i * SLOT;
			int sy = y + HOTBAR_Y;
			ItemStack stack = client.player.getInventory().getStack(i);
			if (!stack.isEmpty()) {
				context.drawItem(stack, sx, sy);
				context.drawItemInSlot(textRenderer, stack, sx, sy);
			}
			if (inSlot(mouseX, mouseY, sx, sy)) {
				HandledScreen.drawSlotHighlight(context, sx, sy, 0);
			}
		}
	}

	private void drawHeld(DrawContext context, int mouseX, int mouseY) {
		ItemStack stack = stackFor(held);
		context.getMatrices().push();
		context.getMatrices().translate(0.0F, 0.0F, 232.0F);
		context.drawItem(stack, mouseX - 8, mouseY - 8);
		context.getMatrices().pop();
	}

	private void drawHover(DrawContext context, int mouseX, int mouseY) {
		// The tabs carry items and no words, so hovering one has to say what it
		// is. Vanilla does exactly this, and it is the thing that makes an
		// unlabelled row of icons learnable rather than a guessing game.
		int hoveredTab = tabAt(mouseX, mouseY);
		if (hoveredTab >= 0) {
			context.drawTooltip(textRenderer, tabName(hoveredTab), mouseX, mouseY);
			return;
		}

		int index = gridAt(mouseX, mouseY);
		List<ItemStack> items = catalogStacks();
		if (index >= 0 && index < items.size()) {
			context.drawItemTooltip(textRenderer, items.get(index), mouseX, mouseY);
			return;
		}
		int slot = slotAt(mouseX, mouseY);
		if (slot >= 0 && client != null && client.player != null) {
			ItemStack stack = client.player.getInventory().getStack(slot);
			if (!stack.isEmpty()) {
				context.drawItemTooltip(textRenderer, stack, mouseX, mouseY);
			}
		}
	}

	// -- the catalog as items ----------------------------------------------

	private List<ItemStack> catalogStacks() {
		CatalogState state = connection.catalog();
		if (state != stacksFor) {
			List<ItemStack> built = new ArrayList<>(state.items().size());
			for (CatalogState.Item item : state.items()) {
				built.add(stackFor(item));
			}
			stacks = List.copyOf(built);
			stacksFor = state;
		}
		return stacks;
	}

	/** Not running and not launching: an app in the catalog is a thing to place. */
	private static ItemStack stackFor(CatalogState.Item item) {
		return AppItem.stack(item.id(), item.iconPath(), item.name(), 1, false, false);
	}

	// -- hit testing -------------------------------------------------------

	private static boolean inSlot(double mouseX, double mouseY, int sx, int sy) {
		return mouseX >= sx && mouseX < sx + 16 && mouseY >= sy && mouseY < sy + 16;
	}

	/** Index into the *current* catalog list under a point, or -1. */
	private int gridAt(double mouseX, double mouseY) {
		int col = cellIndex(mouseX, x + GRID_X, COLS);
		int row = cellIndex(mouseY, y + GRID_Y, ROWS);
		if (col < 0 || row < 0) {
			return -1;
		}
		return (scrollRow + row) * COLS + col;
	}

	/** Hotbar index 0-8 under a point, or -1. */
	private int slotAt(double mouseX, double mouseY) {
		int col = cellIndex(mouseX, x + GRID_X, COLS);
		return cellIndex(mouseY, y + HOTBAR_Y, 1) < 0 ? -1 : col;
	}

	private int tabAt(double mouseX, double mouseY) {
		if (mouseY < y - 28 || mouseY >= y - 28 + TAB_H) {
			return -1;
		}
		int offset = (int) mouseX - x;
		if (offset < 0) {
			return -1;
		}
		int index = offset / TAB_PITCH;
		// Reject the seam between two tabs rather than rounding into a
		// neighbour: a misplaced click should do nothing.
		if (index >= TABS.size() || offset % TAB_PITCH >= TAB_W) {
			return -1;
		}
		return index;
	}

	/**
	 * Which cell of a row or column a point is in, or -1 for the gap.
	 *
	 * <p>Slots are 18 apart and 16 across, so there are two pixels of panel
	 * between them; a click there should do nothing rather than act on
	 * whichever neighbour rounding picks.
	 */
	private static int cellIndex(double position, int origin, int count) {
		int offset = (int) position - origin;
		if (offset < 0) {
			return -1;
		}
		int index = offset / SLOT;
		if (index >= count || offset % SLOT >= 16) {
			return -1;
		}
		return index;
	}

	private boolean inPanel(double mouseX, double mouseY) {
		return mouseX >= x && mouseX < x + BG_W && mouseY >= y && mouseY < y + BG_H;
	}

	// -- input -------------------------------------------------------------

	@Override
	public boolean mouseClicked(double mouseX, double mouseY, int button) {
		int t = tabAt(mouseX, mouseY);
		if (t >= 0) {
			if (t != tab) {
				tab = t;
				scrollRow = 0;
				scrolling = false;
				syncSearchVisibility();
				query();
			}
			return true;
		}

		if (button == 0 && inScrollbar(mouseX, mouseY)) {
			scrolling = maxScroll() > 0;
			if (scrolling) {
				scrollTo(mouseY);
			}
			return true;
		}

		int slot = slotAt(mouseX, mouseY);
		if (slot >= 0) {
			clickSlot(slot + 1);
			return true;
		}

		int index = gridAt(mouseX, mouseY);
		if (index >= 0) {
			List<CatalogState.Item> items = connection.catalog().items();
			if (held != null) {
				// Putting an app back into the catalog cancels the carry. If it
				// came from a slot, that is also how you empty the slot.
				drop();
			} else if (index < items.size()) {
				held = items.get(index);
				heldFrom = 0;
			}
			return true;
		}

		if (held != null && !inPanel(mouseX, mouseY)) {
			// Dropped outside: the creative-inventory gesture for throwing
			// something away. From a slot, that clears the slot.
			drop();
			return true;
		}

		return super.mouseClicked(mouseX, mouseY, button);
	}

	private void clickSlot(int slot) {
		if (held != null) {
			connection.slotAssign(slot, held.id());
			if (heldFrom != 0 && heldFrom != slot) {
				connection.slotClear(heldFrom);
			}
			held = null;
			heldFrom = 0;
			return;
		}

		TaskbarState.Slot current = connection.state().at(slot - 1);
		if (current == null || !current.assigned()) {
			return;
		}
		// Picking up from a slot does not clear it yet — see heldFrom.
		held = new CatalogState.Item(current.app(), current.displayName(),
				current.iconPath(), "");
		heldFrom = slot;
	}

	/** Let go of the held app, emptying its source slot if it had one. */
	private void drop() {
		if (heldFrom != 0) {
			connection.slotClear(heldFrom);
		}
		held = null;
		heldFrom = 0;
	}

	@Override
	public boolean mouseScrolled(double mouseX, double mouseY, double horizontal, double vertical) {
		scrollRow = MathHelper.clamp(scrollRow - (int) Math.signum(vertical), 0, maxScroll());
		return true;
	}

	@Override
	public boolean mouseDragged(double mouseX, double mouseY, int button,
			double deltaX, double deltaY) {
		if (scrolling) {
			scrollTo(mouseY);
			return true;
		}
		return super.mouseDragged(mouseX, mouseY, button, deltaX, deltaY);
	}

	@Override
	public boolean mouseReleased(double mouseX, double mouseY, int button) {
		scrolling = false;
		return super.mouseReleased(mouseX, mouseY, button);
	}

	/** The scrollbar's grab area, vanilla's {@code isClickInScrollbar}. */
	private boolean inScrollbar(double mouseX, double mouseY) {
		return mouseX >= x + SCROLLER_X && mouseX < x + SCROLLER_X + SCROLLER_GRAB_W
				&& mouseY >= y + GRID_Y && mouseY < y + GRID_Y + SCROLLER_TRACK;
	}

	/** How many rows are hidden below the five on screen. */
	private int maxScroll() {
		int totalRows = (connection.catalog().items().size() + COLS - 1) / COLS;
		return Math.max(0, totalRows - ROWS);
	}

	/**
	 * Put the scroller where the cursor is.
	 *
	 * <p>Vanilla's arithmetic, kept verbatim so the feel matches: the cursor
	 * holds the middle of the 15px scroller, and the travel is the track less
	 * the scroller. It works in a 0..1 fraction; we round that onto whole rows,
	 * because this list scrolls by the row and a half-row offset would show two
	 * clipped ranks of icons instead of five clean ones.
	 */
	private void scrollTo(double mouseY) {
		int top = y + GRID_Y;
		float fraction = ((float) mouseY - top - 7.5F) / (SCROLLER_TRACK - 15.0F);
		scrollRow = Math.round(MathHelper.clamp(fraction, 0.0F, 1.0F) * maxScroll());
	}

	@Override
	public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
		// The search box owns the keyboard while it is focused, or typing "1"
		// into it would assign an app instead of searching.
		if (search.isVisible() && search.isFocused() && keyCode != GLFW.GLFW_KEY_ESCAPE) {
			return super.keyPressed(keyCode, scanCode, modifiers);
		}

		if (held != null && keyCode >= GLFW.GLFW_KEY_1 && keyCode <= GLFW.GLFW_KEY_9) {
			clickSlot(keyCode - GLFW.GLFW_KEY_1 + 1);
			return true;
		}

		return super.keyPressed(keyCode, scanCode, modifiers);
	}
}
