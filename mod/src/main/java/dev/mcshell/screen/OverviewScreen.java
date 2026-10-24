package dev.mcshell.screen;

import dev.mcshell.MCShellClient;
import dev.mcshell.command.CommandLog;
import dev.mcshell.net.DaemonConnection;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.OrderedText;
import net.minecraft.text.Text;

import java.util.ArrayList;
import java.util.List;

/**
 * Where command output goes when there is too much of it for chat.
 *
 * <p>It used to be the nine hotbar slots as well, drawn big enough to click with
 * a free cursor, and that is gone (M8). The hotbar holds real items now, so the
 * slots were a second hotbar drawn on top of the first one — and an application
 * in your hand answers a right-click in the world directly, which is what the
 * row was for. What is left is the half that had no other home: a scrolling
 * panel for output that outgrew five lines.
 *
 * <p>Still a Screen, and still for the original reason above all others —
 * opening a Screen releases Minecraft's pointer grab, so the cursor becomes free
 * without touching input plumbing.
 */
public final class OverviewScreen extends Screen {
	private static final int PAD = 8;
	/** Roughly the width the nine slots used to take, so it reads as the same panel. */
	private static final int MAX_WIDTH = 428;

	/** Height of one output row: the font, plus a pixel so lines do not touch. */
	private static final int LINE = 10;
	private static final int MIN_OUT_ROWS = 3;
	private static final int MAX_OUT_ROWS = 20;
	/** Rows moved per wheel notch. One at a time is correct and unbearable. */
	private static final int SCROLL_STEP = 3;

	private static final int COLOR_COMMAND = 0xFFB0B0C8;
	private static final int COLOR_STDOUT = 0xFFDDDDDD;
	private static final int COLOR_STDERR = 0xFFFF8080;
	private static final int COLOR_NOTE = 0xFFFFD060;

	private final DaemonConnection connection;
	private final CommandLog log;

	/** Laid out in init(), because the sizes depend on the GUI scale. */
	private int left;
	private int panelWidth;
	private int panelTop;
	private int panelBottom;
	private int outTop;
	private int outRows;
	private int outHeight;

	/**
	 * The transcript wrapped to the panel's width.
	 *
	 * <p>Cached rather than rebuilt per frame: wrapping five hundred lines every
	 * frame to draw twenty of them would be the most expensive thing this mod
	 * does. {@link CommandLog#revision()} says when it is stale.
	 */
	private List<Row> wrapped = new ArrayList<>();
	private int wrappedRevision = -1;
	private int wrappedWidth = -1;

	/**
	 * How many rows above the bottom the view sits. Zero pins it to the newest
	 * line, so a running command scrolls itself while the reader is at the
	 * bottom and stays put while they are reading further up.
	 */
	private int scroll;
	/** Whether the output panel's scrollbar is being dragged. */
	private boolean scrolling;

	private record Row(OrderedText text, int color) {
	}

	public OverviewScreen(DaemonConnection connection, CommandLog log) {
		super(Text.translatable("mcshell.overview.title"));
		this.connection = connection;
		this.log = log;
	}

	@Override
	protected void init() {
		panelWidth = Math.max(120, Math.min(MAX_WIDTH, width - 4 * PAD));
		left = (width - panelWidth) / 2;

		// The title band above and the hint below are fixed; whatever height is
		// left over decides how many rows fit, so a small screen shows fewer
		// lines rather than running off the bottom edge.
		int furniture = 20 + 20;
		int room = height - furniture - 4 * PAD;
		outRows = log.isEmpty() ? 0
				: Math.max(MIN_OUT_ROWS, Math.min(MAX_OUT_ROWS, room / LINE));
		outHeight = outRows == 0 ? 0 : outRows * LINE + 6;

		int panelH = furniture + (outHeight == 0 ? 0 : outHeight + 6);
		panelTop = Math.max(PAD, (height - panelH) / 2);
		outTop = panelTop + 20;
		panelBottom = outTop + (outHeight == 0 ? 0 : outHeight + 6) + 20;

		// The panel width decides the wrap, and the GUI scale can change under
		// a resize while the screen is open.
		wrappedRevision = -1;
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

		// The first command of the session can land while this screen is already
		// open — from `mcsh`, or from chat with the panel left up. It has to
		// appear for it, and the layout above decided its height back when there
		// was nothing to show.
		if (log.isEmpty() == (outRows > 0)) {
			init();
		}

		context.fill(left - PAD, panelTop, left + panelWidth + PAD, panelBottom, 0xC0101018);
		context.drawBorder(left - PAD, panelTop, panelWidth + 2 * PAD, panelBottom - panelTop,
				0xFF3A3A4A);

		// A dead daemon looks exactly like an empty panel, so say which it is.
		boolean live = connection.connected();
		context.drawCenteredTextWithShadow(textRenderer,
				Text.translatable(live ? "mcshell.overview.title" : "mcshell.overview.disconnected"),
				width / 2, panelTop + 7, live ? 0xFFFFFFFF : 0xFFFF6666);

		if (outRows > 0) {
			drawOutput(context);
			context.drawCenteredTextWithShadow(textRenderer,
					Text.translatable("mcshell.overview.hint_output"),
					width / 2, panelBottom - 14, 0xFF8888A0);
		} else {
			context.drawCenteredTextWithShadow(textRenderer,
					Text.translatable("mcshell.overview.nothing"),
					width / 2, panelTop + 26, 0xFF8888A0);
		}
	}

	// -- output panel ------------------------------------------------------

	private void drawOutput(DrawContext context) {
		rewrap();

		int boxLeft = left;
		int boxRight = left + panelWidth;
		context.fill(boxLeft, outTop, boxRight, outTop + outHeight, 0x60000000);
		context.drawBorder(boxLeft, outTop, boxRight - boxLeft, outHeight, 0xFF2A2A38);

		// Where the last command ran. `cd` is a daemon builtin, so without this
		// the working directory would be invisible between commands.
		if (!log.cwd().isEmpty()) {
			String cwd = textRenderer.trimToWidth(log.cwd(), panelWidth / 3);
			context.drawTextWithShadow(textRenderer, cwd, boxLeft, panelTop + 7, 0xFF707088);
		}

		int first = Math.max(0, wrapped.size() - outRows - scroll);
		int last = Math.min(wrapped.size(), first + outRows);
		for (int i = first; i < last; i++) {
			Row row = wrapped.get(i);
			context.drawTextWithShadow(textRenderer, row.text(),
					boxLeft + 4, outTop + 3 + (i - first) * LINE, row.color());
		}

		drawOutputScrollbar(context, boxRight);
	}

	private void drawOutputScrollbar(DrawContext context, int boxRight) {
		int total = wrapped.size();
		if (total <= outRows) {
			return;
		}
		int trackX = boxRight - 4;
		context.fill(trackX, outTop + 1, trackX + 3, outTop + outHeight - 1, 0x40000000);

		int trackH = outHeight - 2;
		int thumbH = Math.max(8, trackH * outRows / total);
		int span = trackH - thumbH;
		int maxScroll = total - outRows;
		// scroll counts up from the bottom, so the thumb runs the other way.
		int thumbY = outTop + 1 + span * (maxScroll - scroll) / maxScroll;
		context.fill(trackX, thumbY, trackX + 3, thumbY + thumbH, 0xFF6A6A80);
	}
	/** Rewrap the transcript if it, or the width available to it, has changed. */
	private void rewrap() {
		int usable = panelWidth - 12;
		if (wrappedRevision == log.revision() && wrappedWidth == usable) {
			return;
		}
		int before = wrapped.size();
		wrapped = new ArrayList<>();
		for (CommandLog.Line line : log.lines()) {
			int color = switch (line.kind()) {
				case COMMAND -> COLOR_COMMAND;
				case STDERR -> COLOR_STDERR;
				case NOTE -> COLOR_NOTE;
				default -> COLOR_STDOUT;
			};
			List<OrderedText> parts = textRenderer.wrapLines(Text.literal(line.text()), usable);
			if (parts.isEmpty()) {
				// A blank line in output is a blank line on screen; wrapping an
				// empty string yields nothing at all.
				wrapped.add(new Row(OrderedText.EMPTY, color));
				continue;
			}
			for (OrderedText part : parts) {
				wrapped.add(new Row(part, color));
			}
		}
		wrappedRevision = log.revision();
		// Somebody reading further up should keep reading the same lines while a
		// command streams underneath them. Since `scroll` counts from the
		// bottom, holding position means growing it as the bottom moves away —
		// but only when they have scrolled at all: at the bottom, following the
		// output live is the whole point.
		if (scroll > 0 && wrappedWidth == usable && wrapped.size() > before) {
			scroll += wrapped.size() - before;
		}
		wrappedWidth = usable;
		scroll = Math.min(scroll, Math.max(0, wrapped.size() - outRows));
	}

	@Override
	public boolean mouseClicked(double mouseX, double mouseY, int button) {
		if (button == 0 && inScrollbar(mouseX, mouseY)) {
			scrolling = maxScroll() > 0;
			if (scrolling) {
				scrollTo(mouseY);
			}
			return true;
		}
		return super.mouseClicked(mouseX, mouseY, button);
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

	private int maxScroll() {
		return Math.max(0, wrapped.size() - outRows);
	}

	/** The three-pixel bar, with a few either side so it can be grabbed. */
	private boolean inScrollbar(double mouseX, double mouseY) {
		if (outRows == 0 || maxScroll() == 0) {
			return false;
		}
		int trackX = left + panelWidth - 4;
		return mouseX >= trackX - 3 && mouseX < trackX + 6
				&& mouseY >= outTop && mouseY < outTop + outHeight;
	}

	/**
	 * Drag the output panel's thumb.
	 *
	 * <p>This one counts backwards: {@code scroll} is lines up <em>from the
	 * bottom</em>, because a transcript follows its newest line. So the top of
	 * the track is the largest scroll, not the smallest, and the fraction is
	 * inverted before it becomes a line count.
	 */
	private void scrollTo(double mouseY) {
		int trackH = outHeight - 2;
		int thumb = Math.max(8, trackH * outRows / Math.max(1, wrapped.size()));
		int travel = Math.max(1, trackH - thumb);
		double fraction = (mouseY - (outTop + 1) - thumb / 2.0) / travel;
		fraction = Math.max(0.0, Math.min(1.0, fraction));
		scroll = (int) Math.round((1.0 - fraction) * maxScroll());
	}

	@Override
	public boolean mouseScrolled(double mouseX, double mouseY, double horizontal, double vertical) {
		if (outRows == 0) {
			return super.mouseScrolled(mouseX, mouseY, horizontal, vertical);
		}
		int maxScroll = Math.max(0, wrapped.size() - outRows);
		scroll = Math.max(0, Math.min(maxScroll,
				scroll + (int) Math.signum(vertical) * SCROLL_STEP));
		return true;
	}

	// -- input -------------------------------------------------------------

	@Override
	public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
		// The key that opened the panel closes it. Key bindings do not tick
		// while a Screen is open, so this cannot come through the usual path.
		if (MCShellClient.overviewKey().matchesKey(keyCode, scanCode)) {
			close();
			return true;
		}
		return super.keyPressed(keyCode, scanCode, modifiers);
	}
}
