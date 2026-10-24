package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import dev.mcshell.net.ProcessState;
import dev.mcshell.net.StatsState;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.tooltip.Tooltip;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.screen.ScreenTexts;
import net.minecraft.text.Text;
import net.minecraft.util.Util;

import java.util.List;
import java.util.Locale;

/**
 * The Statistics screen, about the machine rather than the world.
 *
 * <p>Three tabs, standing exactly where Minecraft's three stood, in vanilla's
 * geometry: the body between {@code y = 33} and {@code height - 58}, a row of
 * three 120-wide tab buttons in the footer, and Done under them. Vanilla's own
 * screen is buried rather than moved aside — how many zombies you have killed
 * in a void world with mob spawning off is not a number anyone came to read.
 *
 * <p><b>General</b> and <b>Disks</b> are readouts, pulled when the tab opens.
 * <b>Processes</b> is live, and only while it is on screen: the daemon samples
 * nothing until asked and stops the moment this screen closes, because a
 * sample costs it about 23ms and a task manager nobody is looking at is pure
 * waste.
 *
 * <p>The process table is the one place in this project where function is
 * allowed to win an argument with the look. It still borrows what it can —
 * vanilla's own sort arrows off the statistics sprite sheet, vanilla's list
 * scrollbar — but it is a table with right-aligned numeric columns, because
 * that is what makes columns of numbers comparable and nothing in Minecraft's
 * vocabulary does the same job.
 */
public final class MachineStatsScreen extends Screen {
	// -- vanilla StatsScreen geometry --------------------------------------
	private static final int TOP = 33;
	private static final int BOTTOM_BAR = 58;
	private static final int ROW_W = 320;
	private static final int TAB_W = 120;
	private static final int BUTTON_H = 20;
	private static final int GAP = 5;

	private static final int ROW_H = 12;
	private static final int GROUP_H = 16;
	private static final int BAR_H = 3;

	private static final int LABEL = 0xFFDDDDDD;
	private static final int VALUE = 0xFFFFFFFF;
	private static final int DIM = 0xFF9A9A9A;
	private static final int HEADING = 0xFFA0A0B0;
	private static final int ERROR = 0xFFFF6666;
	private static final int BAR_BACK = 0xFF1A1A1A;
	private static final int BAR_FILL = 0xFF55C455;
	private static final int BAR_WARN = 0xFFE0A040;
	private static final int BAR_FULL = 0xFFD05050;
	private static final int SELECTED = 0x60FFFFFF;

	// Vanilla's list scrollbar, from EntryListWidget.
	private static final int SCROLLBAR_W = 6;
	private static final int SCROLL_TRACK = 0xFF000000;
	private static final int SCROLL_THUMB = 0xFF808080;
	private static final int SCROLL_THUMB_FACE = 0xFFC0C0C0;

	private static final long NOTICE_MS = 6000;
	/** More rows than a screen can show, so scrolling has somewhere to go. */
	private static final int PROCESS_LIMIT = 128;

	private static final String GENERAL = "general";
	private static final String PROCESSES = "processes";
	private static final String DISKS = "disks";

	/** One sortable column of the process table. */
	private record Column(String key, String title, int right, int width, boolean numeric) {
	}

	/**
	 * The table, laid out from the right so the columns of numbers line up and
	 * the command — the only field with no natural width — takes what is left.
	 */
	private static final List<Column> COLUMNS = List.of(
			new Column("cpu", "CPU%", 44, 44, true),
			new Column("mem", "MEM%", 90, 40, true),
			new Column("pid", "PID", 134, 40, true),
			new Column("name", "PROCESS", 0, 0, false));
	private static final int USER_X = 140;
	private static final int USER_W = 56;
	private static final int NAME_X = USER_X + USER_W;

	private final DaemonConnection connection;
	private final Screen parent;

	private String tab = GENERAL;
	private int scroll;
	private int contentHeight;

	private String sort = "cpu";
	private boolean desc = true;
	private int selected;

	private String notice;
	private long noticeUntil;

	/**
	 * Whether the scrollbar is being dragged.
	 *
	 * <p>Held until the button comes up, even if the pointer wanders off the
	 * bar, because that is what vanilla does and anything else feels like the
	 * bar is slipping out of your hand.
	 */
	private boolean scrolling;

	private ButtonWidget killButton;
	/** What the kill button's tooltip was last built for, so it is not rebuilt every frame. */
	private int tooltipFor = -1;
	/** Whether the daemon was up last frame, so a reconnect can re-ask. */
	private boolean wasConnected;

	public MachineStatsScreen(DaemonConnection connection, Screen parent) {
		super(Text.translatable("mcshell.stats.title"));
		this.connection = connection;
		this.parent = parent;
	}

	// -- lifecycle ---------------------------------------------------------

	@Override
	protected void init() {
		int row = height - BOTTOM_BAR + 8;
		int x = (width - (TAB_W * 3 + GAP * 2)) / 2;
		addTab(x, row, GENERAL);
		addTab(x + TAB_W + GAP, row, PROCESSES);
		addTab(x + (TAB_W + GAP) * 2, row, DISKS);

		int done = height - 28;
		killButton = addDrawableChild(ButtonWidget.builder(
						Text.translatable("mcshell.stats.kill"), b -> kill())
				.dimensions(10, done, TAB_W, BUTTON_H).build());
		addDrawableChild(ButtonWidget.builder(ScreenTexts.DONE, b -> close())
				.dimensions(width / 2 - 100, done, 200, BUTTON_H).build());

		refresh();
	}

	private void addTab(int x, int y, String name) {
		ButtonWidget button = addDrawableChild(ButtonWidget.builder(
						Text.translatable("mcshell.stats.tab." + name), b -> select(name))
				.dimensions(x, y, TAB_W, BUTTON_H).build());
		button.active = !name.equals(tab);
	}

	private void select(String name) {
		if (name.equals(tab)) {
			return;
		}
		watch(false);
		tab = name;
		scroll = 0;
		selected = 0;
		clearAndInit();
	}

	/** Ask for whatever this tab needs, and stop whatever it does not. */
	private void refresh() {
		if (tab.equals(PROCESSES)) {
			watch(true);
		} else {
			connection.statsQuery(tab);
		}
		syncKillButton();
	}

	private void watch(boolean on) {
		if (tab.equals(PROCESSES) || !on) {
			connection.statsWatch(on, sort, desc, PROCESS_LIMIT);
		}
	}

	@Override
	public void removed() {
		// The stream must stop whichever way the screen goes away — Done,
		// Escape, or a resize that rebuilds it. This is the one call that
		// covers all three.
		connection.statsWatch(false, sort, desc, PROCESS_LIMIT);
		super.removed();
	}

	@Override
	public void close() {
		if (client != null) {
			client.setScreen(parent);
		}
	}

	/**
	 * The world behind a shell screen keeps running — here more than anywhere,
	 * because this screen is a live reading of a machine that does not pause.
	 */
	@Override
	public boolean shouldPause() {
		return false;
	}

	// -- input -------------------------------------------------------------

	@Override
	public boolean mouseClicked(double mouseX, double mouseY, int button) {
		if (button == 0 && inScrollbar(mouseX, mouseY)) {
			scrolling = overflow() > 0;
			if (scrolling) {
				scrollTo(mouseY);
			}
			return true;
		}
		if (tab.equals(PROCESSES)) {
			if (clickedHeader(mouseX, mouseY)) {
				return true;
			}
			if (clickedRow(mouseX, mouseY)) {
				return true;
			}
		}
		return super.mouseClicked(mouseX, mouseY, button);
	}

	private boolean clickedHeader(double mouseX, double mouseY) {
		int y = headerY();
		if (mouseY < y || mouseY >= y + ROW_H) {
			return false;
		}
		int left = left();
		for (Column column : COLUMNS) {
			int start = column.numeric() ? left + column.right() - column.width() : left + NAME_X;
			int end = column.numeric() ? left + column.right() : left + ROW_W;
			if (mouseX >= start && mouseX < end) {
				if (sort.equals(column.key())) {
					desc = !desc;
				} else {
					sort = column.key();
					// Numbers are interesting from the top, names from A.
					desc = column.numeric();
				}
				scroll = 0;
				watch(true);
				if (client != null) {
					client.getSoundManager().play(net.minecraft.client.sound.PositionedSoundInstance
							.master(net.minecraft.sound.SoundEvents.UI_BUTTON_CLICK, 1.0F));
				}
				return true;
			}
		}
		return false;
	}

	private boolean clickedRow(double mouseX, double mouseY) {
		int left = left();
		if (mouseX < left || mouseX >= left + ROW_W) {
			return false;
		}
		int top = listTop();
		if (mouseY < top || mouseY >= viewportBottom()) {
			return false;
		}
		int index = (int) ((mouseY - top + scroll) / ROW_H);
		List<ProcessState.Row> rows = connection.processes().procs();
		if (index < 0 || index >= rows.size()) {
			return false;
		}
		selected = rows.get(index).pid();
		syncKillButton();
		return true;
	}

	@Override
	public boolean mouseScrolled(double mouseX, double mouseY, double horizontal, double vertical) {
		scroll = clamp(scroll - (int) (vertical * ROW_H * 3));
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

	/** The scrollbar's grab area: the bar, plus a little either side of it. */
	private boolean inScrollbar(double mouseX, double mouseY) {
		int x = scrollbarX();
		return mouseX >= x - 1 && mouseX < x + SCROLLBAR_W + 1
				&& mouseY >= listTop() && mouseY < viewportBottom();
	}

	/** How much content there is beyond the viewport, or 0 when it all fits. */
	private int overflow() {
		return Math.max(0, contentHeight - (viewportBottom() - listTop()));
	}

	/**
	 * Put the thumb where the cursor is, holding it by its middle.
	 *
	 * <p>The travel is the viewport less the thumb, which is what makes the
	 * bottom of the track mean the bottom of the list rather than somewhere
	 * short of it.
	 */
	private void scrollTo(double mouseY) {
		int top = listTop();
		int viewport = viewportBottom() - top;
		int thumb = thumbHeight(viewport);
		int travel = Math.max(1, viewport - thumb);
		double fraction = (mouseY - top - thumb / 2.0) / travel;
		scroll = clamp((int) Math.round(Math.max(0.0, Math.min(1.0, fraction)) * overflow()));
	}

	private int thumbHeight(int viewport) {
		return Math.max(32, Math.min(viewport, viewport * viewport / Math.max(1, contentHeight)));
	}

	private int scrollbarX() {
		return left() + ROW_W + 6;
	}

	private int clamp(int value) {
		int viewport = viewportBottom() - listTop();
		return Math.max(0, Math.min(Math.max(0, contentHeight - viewport), value));
	}

	private void kill() {
		if (selected <= 0) {
			return;
		}
		connection.processKill(selected);
	}

	private void syncKillButton() {
		if (killButton == null) {
			return;
		}
		ProcessState.Row row = selectedRow();
		killButton.visible = tab.equals(PROCESSES);
		killButton.active = row != null && !row.protectedProcess();
		if (tooltipFor == selected) {
			return;
		}
		// Rebuilt only when the selection changes. A fresh Tooltip every frame
		// would allocate sixty a second and restart its own delay each time,
		// so it would never actually appear.
		tooltipFor = selected;
		killButton.setTooltip(row == null ? null
				: Tooltip.of(Text.literal(row.protectedProcess()
						? row.name() + " holds this session up"
						: "Send SIGTERM to " + row.name() + " (" + row.pid() + ")")));
	}

	private ProcessState.Row selectedRow() {
		for (ProcessState.Row row : connection.processes().procs()) {
			if (row.pid() == selected) {
				return row;
			}
		}
		return null;
	}

	// -- rendering ---------------------------------------------------------

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		super.render(context, mouseX, mouseY, delta);
		context.drawCenteredTextWithShadow(textRenderer, title, width / 2, 15, VALUE);

		syncKillButton();
		String error = connection.pollError();
		if (error != null) {
			notice = error;
			noticeUntil = Util.getMeasuringTimeMs() + NOTICE_MS;
		}

		// A screen opened before the daemon was up would sit empty forever
		// otherwise: the static tabs are asked once, and that once was a
		// message into a closed socket.
		boolean up = connection.connected();
		if (up && !wasConnected) {
			refresh();
		}
		wasConnected = up;

		if (!connection.connected()) {
			context.drawCenteredTextWithShadow(textRenderer,
					Text.translatable("mcshell.overview.disconnected"), width / 2, TOP + 20, ERROR);
			return;
		}

		if (tab.equals(PROCESSES)) {
			renderProcesses(context, mouseX, mouseY);
		} else {
			renderRows(context, connection.stats(tab).rows());
		}
		drawScrollbar(context);
		drawNotice(context);
	}

	private int left() {
		return (width - ROW_W) / 2;
	}

	private int viewportBottom() {
		return height - BOTTOM_BAR;
	}

	/** Where the list starts: below the summary block on the live tab. */
	private int listTop() {
		return tab.equals(PROCESSES) ? TOP + 40 + ROW_H : TOP;
	}

	private int headerY() {
		return TOP + 40;
	}

	// -- the static tabs ---------------------------------------------------

	private void renderRows(DrawContext context, List<StatsState.Row> rows) {
		int left = left();
		int y = TOP - scroll;
		String group = null;

		context.enableScissor(0, TOP, width, viewportBottom());
		for (StatsState.Row row : rows) {
			if (!row.group().isEmpty() && !row.group().equals(group)) {
				group = row.group();
				y += 4;
				if (visible(y, GROUP_H)) {
					context.drawTextWithShadow(textRenderer, Text.literal(group), left, y, HEADING);
					context.fill(left, y + 10, left + ROW_W, y + 11, 0x40FFFFFF);
				}
				y += GROUP_H;
			}
			int height = rowHeight(row);
			if (visible(y, height)) {
				drawRow(context, row, left, y);
			}
			y += height;
		}
		context.disableScissor();
		contentHeight = y + scroll - TOP;
	}

	/**
	 * How tall a row is, counting every line it draws.
	 *
	 * <p>This existing separately from {@link #drawRow} was the bug: the
	 * detail line was drawn but not measured, so every row that had one was
	 * written over by the row beneath it. One place decides now, and drawing
	 * follows it.
	 */
	private static int rowHeight(StatsState.Row row) {
		int height = ROW_H;
		if (row.hasBar()) {
			height += BAR_H + 2;
		}
		if (!row.detail().isEmpty()) {
			height += ROW_H;
		}
		return height;
	}

	private void drawRow(DrawContext context, StatsState.Row row, int left, int y) {
		context.drawTextWithShadow(textRenderer, Text.literal(row.label()), left, y, LABEL);

		// The value is right-aligned, and what is left after the label is all
		// it may have. A CPU model name is longer than that on any machine, so
		// this is the normal case rather than the edge one.
		int room = ROW_W - textRenderer.getWidth(row.label()) - 8;
		String value = row.value();
		if (textRenderer.getWidth(value) > room) {
			value = textRenderer.trimToWidth(value, Math.max(0, room - 6)) + "…";
		}
		context.drawTextWithShadow(textRenderer, Text.literal(value),
				left + ROW_W - textRenderer.getWidth(value), y, VALUE);

		if (row.hasBar()) {
			int barY = y + ROW_H - 1;
			context.fill(left, barY, left + ROW_W, barY + BAR_H, BAR_BACK);
			int fill = Math.round(Math.min(1.0F, Math.max(0.0F, row.fraction())) * ROW_W);
			if (fill > 0) {
				context.fill(left, barY, left + fill, barY + BAR_H, barColor(row.fraction()));
			}
		}
		if (!row.detail().isEmpty()) {
			// On its own line under the label: a device path is longer than
			// anything it could sit beside. rowHeight() reserves this line.
			int detailY = y + (row.hasBar() ? ROW_H + BAR_H + 2 : ROW_H);
			if (visible(detailY, ROW_H)) {
				context.drawTextWithShadow(textRenderer,
						Text.literal(textRenderer.trimToWidth(row.detail(), ROW_W)),
						left, detailY, DIM);
			}
		}
	}

	/** Green until it matters, amber when it does, red when it is nearly gone. */
	private static int barColor(float fraction) {
		if (fraction >= 0.9F) {
			return BAR_FULL;
		}
		return fraction >= 0.75F ? BAR_WARN : BAR_FILL;
	}

	private boolean visible(int y, int height) {
		return y + height >= TOP && y <= viewportBottom();
	}

	// -- the live tab ------------------------------------------------------

	private void renderProcesses(DrawContext context, int mouseX, int mouseY) {
		ProcessState state = connection.processes();
		int left = left();

		drawGauge(context, left, TOP, "CPU", state.cpu() / 100.0F,
				String.format(Locale.ROOT, "%.1f%%", state.cpu()),
				state.load().isEmpty() ? ""
						: String.format(Locale.ROOT, "load %.2f", state.load().get(0)));
		float memFraction = state.memTotal() == 0 ? 0
				: (float) state.memUsed() / state.memTotal();
		drawGauge(context, left, TOP + 20, "Memory", memFraction,
				bytes(state.memUsed()) + " / " + bytes(state.memTotal()),
				state.count() + " processes");

		drawHeader(context, left);

		int top = listTop();
		context.enableScissor(0, top, width, viewportBottom());
		int y = top - scroll;
		for (ProcessState.Row row : state.procs()) {
			if (visible2(y, top)) {
				drawProcess(context, row, left, y, mouseX, mouseY);
			}
			y += ROW_H;
		}
		context.disableScissor();
		contentHeight = state.procs().size() * ROW_H;
	}

	private boolean visible2(int y, int top) {
		return y + ROW_H >= top && y <= viewportBottom();
	}

	private void drawGauge(DrawContext context, int left, int y, String label,
			float fraction, String value, String detail) {
		context.drawTextWithShadow(textRenderer, Text.literal(label), left, y, LABEL);
		context.drawTextWithShadow(textRenderer, Text.literal(value),
				left + 60, y, VALUE);
		if (!detail.isEmpty()) {
			context.drawTextWithShadow(textRenderer, Text.literal(detail),
					left + ROW_W - textRenderer.getWidth(detail), y, DIM);
		}
		int barY = y + 11;
		context.fill(left, barY, left + ROW_W, barY + BAR_H, BAR_BACK);
		int fill = Math.round(Math.min(1.0F, Math.max(0.0F, fraction)) * ROW_W);
		if (fill > 0) {
			context.fill(left, barY, left + fill, barY + BAR_H, barColor(fraction));
		}
	}

	private void drawHeader(DrawContext context, int left) {
		int y = headerY();
		context.fill(left, y + ROW_H - 1, left + ROW_W, y + ROW_H, 0x40FFFFFF);
		for (Column column : COLUMNS) {
			boolean active = sort.equals(column.key());
			int color = active ? VALUE : HEADING;
			int x;
			if (column.numeric()) {
				x = left + column.right() - textRenderer.getWidth(column.title());
			} else {
				x = left + NAME_X;
			}
			context.drawTextWithShadow(textRenderer, Text.literal(column.title()), x, y, color);
			if (active) {
				drawArrow(context, x + textRenderer.getWidth(column.title()) + 3, y + 3, desc);
			}
		}
		context.drawTextWithShadow(textRenderer, Text.literal("USER"), left + USER_X, y, HEADING);
	}

	/**
	 * A five-pixel sort arrow, drawn rather than blitted.
	 *
	 * <p>Vanilla has sort arrows on this very screen and they are not used
	 * here, which was checked rather than assumed: they are 18x18 sprites
	 * built for an 18-pixel icon column, and how the glyph sits inside that
	 * cell is not visible from the file. Squashing one into a 12-pixel text
	 * row would have been a guess. Three filled rows are not.
	 */
	private static void drawArrow(DrawContext context, int x, int y, boolean down) {
		for (int i = 0; i < 3; i++) {
			int span = down ? 3 - i : i + 1;
			int row = y + i;
			context.fill(x + (3 - span), row, x + (3 + span) - 1, row + 1, 0xFFFFFFFF);
		}
	}

	private void drawProcess(DrawContext context, ProcessState.Row row, int left, int y,
			int mouseX, int mouseY) {
		boolean hovered = mouseX >= left && mouseX < left + ROW_W
				&& mouseY >= y && mouseY < y + ROW_H
				&& mouseY >= listTop() && mouseY < viewportBottom();
		if (row.pid() == selected) {
			context.fill(left, y - 1, left + ROW_W, y + ROW_H - 1, SELECTED);
		} else if (hovered) {
			context.fill(left, y - 1, left + ROW_W, y + ROW_H - 1, 0x30FFFFFF);
		}

		int color = row.protectedProcess() ? DIM : VALUE;
		right(context, String.format(Locale.ROOT, "%.1f", row.cpu()), left + 44, y,
				row.cpu() >= 10 ? BAR_WARN : color);
		right(context, String.format(Locale.ROOT, "%.1f", row.mem()), left + 90, y,
				row.mem() >= 10 ? BAR_WARN : color);
		right(context, Integer.toString(row.pid()), left + 134, y, DIM);
		context.drawTextWithShadow(textRenderer,
				Text.literal(textRenderer.trimToWidth(row.user(), USER_W - 4)),
				left + USER_X, y, DIM);
		context.drawTextWithShadow(textRenderer,
				Text.literal(textRenderer.trimToWidth(row.name(), ROW_W - NAME_X)),
				left + NAME_X, y, color);
	}

	private void right(DrawContext context, String text, int rightEdge, int y, int color) {
		context.drawTextWithShadow(textRenderer, Text.literal(text),
				rightEdge - textRenderer.getWidth(text), y, color);
	}

	private static String bytes(long count) {
		String[] units = {"B", "KB", "MB", "GB", "TB"};
		double value = count;
		int unit = 0;
		while (value >= 1024 && unit < units.length - 1) {
			value /= 1024;
			unit++;
		}
		return String.format(Locale.ROOT, unit <= 1 ? "%.0f %s" : "%.1f %s", value, units[unit]);
	}

	// -- chrome ------------------------------------------------------------

	private void drawNotice(DrawContext context) {
		if (notice == null) {
			return;
		}
		if (Util.getMeasuringTimeMs() > noticeUntil) {
			notice = null;
			return;
		}
		context.drawCenteredTextWithShadow(textRenderer,
				Text.literal(textRenderer.trimToWidth(notice, width - 40)),
				width / 2, viewportBottom() + 4, ERROR);
	}

	private void drawScrollbar(DrawContext context) {
		int top = listTop();
		int viewport = viewportBottom() - top;
		if (contentHeight <= viewport) {
			scroll = 0;
			scrolling = false;
			return;
		}
		scroll = clamp(scroll);
		int x = scrollbarX();
		int thumb = thumbHeight(viewport);
		int travel = viewport - thumb;
		int thumbY = top + (travel * scroll) / Math.max(1, overflow());

		context.fill(x, top, x + SCROLLBAR_W, top + viewport, SCROLL_TRACK);
		context.fill(x, thumbY, x + SCROLLBAR_W, thumbY + thumb, SCROLL_THUMB);
		context.fill(x, thumbY, x + SCROLLBAR_W - 1, thumbY + thumb - 1, SCROLL_THUMB_FACE);
	}
}
