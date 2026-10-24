package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import dev.mcshell.net.SettingsState;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.tooltip.Tooltip;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.client.gui.widget.ClickableWidget;
import net.minecraft.client.gui.widget.CyclingButtonWidget;
import net.minecraft.client.gui.widget.SliderWidget;
import net.minecraft.client.gui.widget.TextFieldWidget;
import net.minecraft.screen.ScreenTexts;
import net.minecraft.text.Text;
import net.minecraft.util.Util;
import net.minecraft.util.Formatting;
import org.lwjgl.glfw.GLFW;

import java.util.ArrayList;
import java.util.List;

/**
 * One machine settings page, drawn from whatever the daemon said is on it.
 *
 * <p>This screen knows nothing about audio, or displays, or keybinds. It knows
 * five row types and how to send a key back with a new value. Adding a setting
 * is a change to the daemon; adding a whole page is a provider and one line in
 * {@link SettingsIntegration}. Nothing here is touched by either.
 *
 * <p>It sits beside the vanilla options screen it mirrors rather than replacing
 * it: the bottom-left button switches lanes, in both directions, so Minecraft's
 * own sound settings are one click away and still exist.
 */
public final class SettingsScreen extends Screen {
	private static final int ROW_H = 20;
	private static final int ROW_STEP = 24;
	private static final int HEADER_H = 16;
	private static final int MAX_ROW_W = 400;
	// Minecraft's own Key Binds row: the action named on the left, the key in a
	// column, Reset after it. Copied because the screen sits next to that one.
	private static final int KEY_W = 100;
	private static final int RESET_W = 50;
	// A text row is laid out like a keybind row — its name on the left, the
	// control in a column — but the column is the rest of the line, because a
	// shell command needs the room and a key combination does not.
	private static final int TEXT_LABEL_W = 70;
	/** The daemon refuses anything longer; there is no point in typing it. */
	private static final int COMMAND_MAX = 256;
	private static final int COL_GAP = 4;
	private static final int TOP = 34;
	private static final int BOTTOM_BAR = 36;
	private static final int SCROLL_STEP = 24;

	private static final int HEADER_COLOR = 0xFFA0A0B0;
	private static final int LABEL_COLOR = 0xFFDDDDDD;
	private static final int DISABLED_COLOR = 0xFF808080;
	private static final int ERROR_COLOR = 0xFFFF6666;
	private static final int HINT_COLOR = 0xFFFFCC44;
	/** How long a refusal stays on screen. Long enough to read twice. */
	private static final long NOTICE_MS = 6000;
	private static final int SEPARATOR = 0xFF000000;

	// Vanilla's own scrollbar, from EntryListWidget: six wide, a black track,
	// a grey thumb with a lighter face. Copied rather than approximated —
	// a scrollbar that is nearly right reads as wrong.
	private static final int SCROLLBAR_W = 6;
	private static final int SCROLL_TRACK = 0xFF000000;
	private static final int SCROLL_THUMB = 0xFF808080;
	private static final int SCROLL_THUMB_FACE = 0xFFC0C0C0;

	private final DaemonConnection connection;
	private final String page;
	private final Screen vanilla;
	private final Text vanillaLabel;

	/** What the widgets were built from, so a push can be spotted by identity. */
	private SettingsState built = null;
	/** Header text and the y it wants, rebuilt with the widgets. */
	private final List<Heading> headings = new ArrayList<>();
	private final List<Entry> entries = new ArrayList<>();
	private int contentHeight;
	private int scroll;
	private boolean wasConnected;

	/** The daemon's last complaint, and when it stops being worth showing. */
	private String notice;
	private long noticeUntil;

	/** Whether the scrollbar is being dragged. Held until the button comes up. */
	private boolean scrolling;

	/** The keybind row waiting for a key, or null. */
	private KeybindButton capturing;
	/** Whether a real key — not just a held modifier — has arrived yet. */
	private boolean sawKey;

	private record Heading(String text, int offset) {
	}

	/**
	 * One row's widgets.
	 *
	 * @param widget the control, or null when the row is only text
	 * @param extra  a second control on the same line: Reset on a keybind that
	 *               has a default, or whatever button the row asked for
	 */
	private record Entry(ClickableWidget widget, ClickableWidget extra,
			SettingsState.Row row, int offset) {
	}

	/**
	 * @param page         the daemon's page name: "audio", "video", "controls"
	 * @param title        this screen's own title
	 * @param vanilla      the Minecraft screen this one stands beside, or null
	 *                     when there is nothing worth crossing back to
	 * @param vanillaLabel what to call it on the button back, or null with it
	 */
	public SettingsScreen(DaemonConnection connection, String page, Text title,
			Screen vanilla, Text vanillaLabel) {
		super(title);
		this.connection = connection;
		this.page = page;
		this.vanilla = vanilla;
		this.vanillaLabel = vanillaLabel;
	}

	@Override
	protected void init() {
		// Ask every time the screen opens. Pushes keep it current afterwards,
		// but the page may have been built before this session connected.
		connection.settingsQuery(page);
		built = null;
		rebuild();

		int y = height - 26;
		// Network has no Minecraft page to cross to: it replaced Open to LAN,
		// which this shell has no business offering. Every other page keeps
		// its button.
		if (vanilla != null && vanillaLabel != null) {
			addDrawableChild(ButtonWidget.builder(vanillaLabel, b -> switchToVanilla())
					.dimensions(10, y, 120, ROW_H).build());
		}
		addDrawableChild(ButtonWidget.builder(ScreenTexts.DONE, b -> close())
				.dimensions(width / 2 - 100, y, 200, ROW_H).build());
	}

	private void switchToVanilla() {
		if (client != null && vanilla != null) {
			// Through the integration, not straight to setScreen: opening a
			// vanilla options screen is redirected back here by default, and
			// this is the one case that means to get past it.
			SettingsIntegration.showVanilla(client, vanilla);
		}
	}

	@Override
	public void close() {
		// Anything half-typed is meant, or it would not have been typed.
		commitTyping();
		// Up one level, to whatever the Minecraft screen we stand beside would
		// have gone back to — Options, normally. Delegating to that screen
		// rather than working out its parent ourselves means Done behaves
		// exactly like vanilla's Done, including committing any option the
		// player changed on the Minecraft side before crossing over.
		if (vanilla != null) {
			vanilla.close();
		} else if (client != null) {
			client.setScreen(null);
		}
	}

	// -- building ----------------------------------------------------------

	private int rowWidth() {
		return Math.min(MAX_ROW_W, width - 40);
	}

	private int viewportBottom() {
		return height - BOTTOM_BAR;
	}

	/** Throw away the rows and build them again from the current schema. */
	private void rebuild() {
		for (Entry entry : entries) {
			remove(entry.widget());
			if (entry.extra() != null) {
				remove(entry.extra());
			}
		}
		entries.clear();
		headings.clear();

		SettingsState state = connection.settings(page);
		built = state;

		int w = rowWidth();
		int x = (width - w) / 2;
		int offset = 0;

		if (state.rows().isEmpty()) {
			contentHeight = 0;
			return;
		}

		String lastGroup = null;
		for (SettingsState.Row row : state.rows()) {
			if (!row.group().equals(lastGroup)) {
				lastGroup = row.group();
				if (!row.group().isEmpty()) {
					headings.add(new Heading(row.group(), offset + 4));
					offset += HEADER_H;
				}
			}
			ClickableWidget widget = widgetFor(row, x, w);
			if (widget != null) {
				widget.active = row.enabled();
				if (!row.detail().isEmpty()) {
					widget.setTooltip(Tooltip.of(Text.literal(row.detail())));
				}
				addDrawableChild(widget);
			}
			ClickableWidget extra = extraFor(row, x, w);
			if (extra != null) {
				addDrawableChild(extra);
			}
			entries.add(new Entry(widget, extra, row, offset));
			offset += ROW_STEP;
		}
		contentHeight = offset;
		clampScroll();
		layout();
	}

	/** The control a row asks for, or null when the row is only text. */
	private ClickableWidget widgetFor(SettingsState.Row row, int x, int w) {
		return switch (row.type()) {
			case FLOAT, INT -> new SettingSlider(row, x, 0, w);
			case BOOL -> CyclingButtonWidget.onOffBuilder()
					.initially(row.flag())
					.build(x, 0, w, ROW_H, Text.literal(row.label()),
							(button, value) -> connection.settingSet(row.key(), (boolean) value));
			case ENUM -> row.options().isEmpty() ? null : enumWidget(row, x, w);
			case KEYBIND -> new KeybindButton(row, x + w - RESET_W - COL_GAP - KEY_W, KEY_W);
			case ACTION -> ButtonWidget.builder(Text.literal(row.label()),
							b -> connection.settingSet(row.key(), true))
					.dimensions(x, 0, w, ROW_H).build();
			case TEXT -> new SettingField(row, x + TEXT_LABEL_W, w - TEXT_LABEL_W);
			case LABEL -> null;
		};
	}

	/**
	 * The button at the right-hand end of a row, or null when it has none.
	 *
	 * <p>Two kinds share the column and cannot both want it. A row the daemon
	 * gave an {@code extra_key} gets that button and the screen learns nothing
	 * about what pressing it does — it is an {@code action} row that happens to
	 * sit on a line with something else. Otherwise it is Reset, on a keybind
	 * that has a default, greyed while it is already at it.
	 */
	private ClickableWidget extraFor(SettingsState.Row row, int x, int w) {
		if (row.hasExtra()) {
			ButtonWidget button = ButtonWidget.builder(Text.literal(row.extraLabel()),
							b -> connection.settingSet(row.extraKey(), true))
					.dimensions(x + w - RESET_W, 0, RESET_W, ROW_H).build();
			button.active = row.enabled();
			return button;
		}
		if (row.type() != SettingsState.Type.KEYBIND || !row.hasDefault()) {
			return null;
		}
		ButtonWidget reset = ButtonWidget.builder(
						Text.translatable("mcshell.settings.reset"),
						// An ordinary set, carrying the value the daemon said
						// the default was. There is no reset message and no
						// need for one.
						b -> connection.settingSet(row.key(), row.defaultChoice()))
				.dimensions(x + w - RESET_W, 0, RESET_W, ROW_H).build();
		reset.active = !row.isDefault();
		return reset;
	}

	private ClickableWidget enumWidget(SettingsState.Row row, int x, int w) {
		int selected = Math.max(0, row.indexOfChoice());
		return CyclingButtonWidget.<SettingsState.Option>builder(
						option -> Text.literal(trim(option.label(), w - 100)))
				.values(row.options())
				.initially(row.options().get(selected))
				.build(x, 0, w, ROW_H, Text.literal(row.label()),
						(button, option) -> connection.settingSet(row.key(), option.id()));
	}

	private String trim(String text, int max) {
		String cut = textRenderer.trimToWidth(text, Math.max(20, max));
		return cut.length() == text.length() ? text : cut + "…";
	}

	/** Put every widget where the current scroll says it goes. */
	private void layout() {
		int top = TOP - scroll;
		for (Entry entry : entries) {
			int y = top + entry.offset();
			// Cull anything not wholly inside the viewport, so a half-drawn row
			// cannot be clicked where it overlaps the buttons below it.
			boolean visible = y >= TOP && y + ROW_H <= viewportBottom();
			place(entry.widget(), y, visible);
			place(entry.extra(), y, visible);
		}
	}

	private static void place(ClickableWidget widget, int y, boolean visible) {
		if (widget != null) {
			widget.setY(y);
			widget.visible = visible;
		}
	}

	private void clampScroll() {
		int overflow = Math.max(0, contentHeight - (viewportBottom() - TOP));
		scroll = Math.clamp(scroll, 0, overflow);
	}

	/**
	 * A row's text field, which tells the daemon when you are done rather than
	 * as you type.
	 *
	 * <p>Per-keystroke would be a message a character and — because every
	 * accepted set re-pushes the whole page — a rebuild a character, which
	 * throws away the widget being typed into. So the value is committed on
	 * Enter, on losing focus, and on the way out of the screen, and
	 * {@link #sent} keeps those three from saying the same thing twice.
	 */
	private final class SettingField extends TextFieldWidget {
		private final SettingsState.Row row;
		/** What the daemon has already been told. */
		private String sent;

		private SettingField(SettingsState.Row row, int x, int w) {
			super(SettingsScreen.this.textRenderer, x, 0, w, ROW_H,
					Text.literal(row.label()));
			this.row = row;
			this.sent = row.text();
			setMaxLength(COMMAND_MAX);
			setText(row.text());
			if (!row.placeholder().isEmpty()) {
				setPlaceholder(Text.literal(row.placeholder()).formatted(Formatting.DARK_GRAY));
			}
			setEditable(row.enabled());
		}

		void commit() {
			String text = getText();
			if (text.equals(sent)) {
				return;
			}
			sent = text;
			connection.settingSet(row.key(), text);
		}

		@Override
		public void setFocused(boolean focused) {
			boolean was = isFocused();
			super.setFocused(focused);
			if (was && !focused) {
				commit();
			}
		}

		@Override
		public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
			if (isFocused() && (keyCode == GLFW.GLFW_KEY_ENTER
					|| keyCode == GLFW.GLFW_KEY_KP_ENTER)) {
				commit();
				setFocused(false);
				return true;
			}
			return super.keyPressed(keyCode, scanCode, modifiers);
		}
	}

	/** Whether a text field is being typed into, and so must not be rebuilt. */
	private boolean isTyping() {
		for (Entry entry : entries) {
			if (entry.widget() instanceof SettingField field && field.isFocused()) {
				return true;
			}
		}
		return false;
	}

	/**
	 * Push whatever is in the focused field before anything else happens.
	 *
	 * <p>Vanilla moves focus <em>after</em> the click has been handled, so a
	 * click on "Add binding" would otherwise run the button and only then hear
	 * about the command that was typed next to it.
	 */
	private void commitTyping() {
		for (Entry entry : entries) {
			if (entry.widget() instanceof SettingField field && field.isFocused()) {
				field.commit();
			}
		}
	}

	// -- key capture -------------------------------------------------------

	private static boolean isModifier(int keyCode) {
		return keyCode >= GLFW.GLFW_KEY_LEFT_SHIFT && keyCode <= GLFW.GLFW_KEY_RIGHT_SUPER;
	}

	private void beginCapture(KeybindButton button) {
		if (capturing != null) {
			capturing.stopCapture();
		}
		capturing = button;
		sawKey = false;
		button.startCapture();
	}

	private void endCapture() {
		if (capturing != null) {
			capturing.stopCapture();
			capturing = null;
		}
	}

	@Override
	public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
		if (capturing == null) {
			return super.keyPressed(keyCode, scanCode, modifiers);
		}
		if (keyCode == GLFW.GLFW_KEY_ESCAPE) {
			endCapture();
			return true;
		}
		if (isModifier(keyCode)) {
			// Wait: the player is on their way to a combination, and binding
			// Shift the moment they reach for Shift+F1 would be maddening.
			return true;
		}
		sawKey = true;
		connection.settingSetKey(capturing.row.key(), keyCode, modifiers);
		endCapture();
		return true;
	}

	@Override
	public boolean keyReleased(int keyCode, int scanCode, int modifiers) {
		// A modifier let go with nothing pressed after it was meant on its own.
		// Sway users really do bind a bare Super, and waiting for a second key
		// that is never coming would make that impossible to express.
		if (capturing != null && isModifier(keyCode) && !sawKey) {
			connection.settingSetKey(capturing.row.key(), keyCode, modifiers);
			endCapture();
			return true;
		}
		return super.keyReleased(keyCode, scanCode, modifiers);
	}

	@Override
	public boolean mouseClicked(double mouseX, double mouseY, int button) {
		// While a capture is armed, a click only cancels it. Otherwise a click
		// meant as "never mind" would land on whatever was underneath, and a
		// click on the armed row itself would silently re-arm it.
		if (capturing != null) {
			endCapture();
			return true;
		}
		commitTyping();
		if (button == 0 && inScrollbar(mouseX, mouseY)) {
			scrolling = overflow() > 0;
			if (scrolling) {
				scrollTo(mouseY);
			}
			return true;
		}
		return super.mouseClicked(mouseX, mouseY, button);
	}

	// -- input and drawing -------------------------------------------------

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

	private int scrollbarX() {
		return (width + rowWidth()) / 2 + 6;
	}

	private int overflow() {
		return Math.max(0, contentHeight - (viewportBottom() - TOP));
	}

	private int thumbHeight(int viewport) {
		return Math.max(32, Math.min(viewport, viewport * viewport / Math.max(1, contentHeight)));
	}

	/** The bar, plus a pixel either side, so it can be grabbed rather than hunted. */
	private boolean inScrollbar(double mouseX, double mouseY) {
		int x = scrollbarX();
		return mouseX >= x - 1 && mouseX < x + SCROLLBAR_W + 1
				&& mouseY >= TOP && mouseY < viewportBottom();
	}

	/** Hold the thumb by its middle, the way vanilla's lists do. */
	private void scrollTo(double mouseY) {
		int viewport = viewportBottom() - TOP;
		int thumb = thumbHeight(viewport);
		int travel = Math.max(1, viewport - thumb);
		double fraction = (mouseY - TOP - thumb / 2.0) / travel;
		scroll = (int) Math.round(Math.max(0.0, Math.min(1.0, fraction)) * overflow());
		clampScroll();
		layout();
	}

	@Override
	public boolean mouseScrolled(double mouseX, double mouseY, double horizontal, double vertical) {
		if (contentHeight > viewportBottom() - TOP) {
			scroll -= (int) Math.signum(vertical) * SCROLL_STEP;
			clampScroll();
			layout();
			return true;
		}
		return super.mouseScrolled(mouseX, mouseY, horizontal, vertical);
	}

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		// A push replaces the whole page, so rebuild on identity. Never while a
		// slider is being dragged, a key is awaited, or a field is being typed
		// into: the daemon echoing our own change back would otherwise yank the
		// handle out from under the mouse, throw away the row that is waiting
		// for a keypress, or delete the half-written command mid-word. The push
		// is not lost — `built` is compared by identity, so it lands on the
		// first frame after the player is done.
		// A daemon restart drops every page it had sent. Ask again when it
		// comes back, or the screen stays empty until it is reopened.
		boolean connected = connection.connected();
		if (connected && !wasConnected) {
			connection.settingsQuery(page);
		}
		wasConnected = connected;

		// Anything the daemon refused, said where the refusal happened rather
		// than in a log file nobody has open.
		String error = connection.pollError();
		if (error != null) {
			notice = error;
			noticeUntil = Util.getMeasuringTimeMs() + NOTICE_MS;
		}

		SettingsState current = connection.settings(page);
		if (current != built && !isDragging() && capturing == null && !isTyping()) {
			rebuild();
		}

		// Minecraft's screens do not darken the world for free: each one asks
		// for it. Without this the page floats over an undimmed world and the
		// text has to compete with whatever happens to be behind it.
		renderBackground(context, mouseX, mouseY, delta);
		super.render(context, mouseX, mouseY, delta);

		context.drawCenteredTextWithShadow(textRenderer, title, width / 2, 14, 0xFFFFFFFF);
		// The bars vanilla puts above and below a scrolling list, so the title
		// and the buttons read as furniture rather than as more content.
		context.fill(0, TOP - 3, width, TOP - 1, SEPARATOR);
		context.fill(0, viewportBottom() + 1, width, viewportBottom() + 3, SEPARATOR);

		if (entries.isEmpty()) {
			Text empty = connection.connected()
					? Text.translatable("mcshell.settings.empty")
					: Text.translatable("mcshell.overview.disconnected");
			context.drawCenteredTextWithShadow(textRenderer, empty, width / 2, height / 2, DISABLED_COLOR);
			return;
		}

		int x = (width - rowWidth()) / 2;
		int top = TOP - scroll;
		for (Heading heading : headings) {
			int y = top + heading.offset();
			if (fits(y)) {
				// Centred, the way vanilla heads a section of its own lists.
				context.drawCenteredTextWithShadow(textRenderer,
						Text.literal(heading.text()), width / 2, y, HEADER_COLOR);
			}
		}
		// Two kinds of text drawn beside the widgets: a keybind's action, which
		// lives in the row's left column, and rows that are only text at all —
		// "Nothing is playing".
		int labelWidth = rowWidth() - RESET_W - COL_GAP - KEY_W - 8;
		for (Entry entry : entries) {
			SettingsState.Row row = entry.row();
			// Two row types put their control in a column and their name to the
			// left of it. Everything else either carries its own label inside
			// the widget or has no widget at all.
			boolean keybind = row.type() == SettingsState.Type.KEYBIND;
			boolean text_ = row.type() == SettingsState.Type.TEXT;
			if (entry.widget() != null && !keybind && !text_) {
				continue;
			}
			int y = top + entry.offset() + 6;
			if (!fits(y)) {
				continue;
			}
			String text = keybind ? trim(row.label(), labelWidth)
					: text_ ? trim(row.label(), TEXT_LABEL_W - 8) : row.label();
			context.drawTextWithShadow(textRenderer, Text.literal(text),
					x + 4, y, row.enabled() ? LABEL_COLOR : DISABLED_COLOR);
		}

		drawScrollbar(context);
		drawNotice(context);
	}

	/**
	 * The line under the list: why the last change was refused, or — while a
	 * key is awaited — the one thing about capturing that surprises people.
	 */
	private void drawNotice(DrawContext context) {
		if (capturing != null) {
			context.drawCenteredTextWithShadow(textRenderer,
					Text.translatable("mcshell.settings.capture_hint"),
					width / 2, viewportBottom() + 6, HINT_COLOR);
			return;
		}
		if (notice == null) {
			return;
		}
		if (Util.getMeasuringTimeMs() > noticeUntil) {
			notice = null;
			return;
		}
		context.drawCenteredTextWithShadow(textRenderer,
				Text.literal(textRenderer.trimToWidth(notice, width - 40)),
				width / 2, viewportBottom() + 6, ERROR_COLOR);
	}

	/** Whether a line of text at this y is wholly inside the scrolling area. */
	private boolean fits(int y) {
		return y >= TOP && y + textRenderer.fontHeight <= viewportBottom();
	}

	private void drawScrollbar(DrawContext context) {
		int viewport = viewportBottom() - TOP;
		if (contentHeight <= viewport) {
			return;
		}
		int x = scrollbarX();
		int thumb = thumbHeight(viewport);
		int travel = viewport - thumb;
		int overflow = overflow();
		int thumbY = TOP + (overflow == 0 ? 0 : travel * scroll / overflow);

		context.fill(x, TOP, x + SCROLLBAR_W, TOP + viewport, SCROLL_TRACK);
		context.fill(x, thumbY, x + SCROLLBAR_W, thumbY + thumb, SCROLL_THUMB);
		context.fill(x, thumbY, x + SCROLLBAR_W - 1, thumbY + thumb - 1, SCROLL_THUMB_FACE);
	}

	/**
	 * A key combination, and a click that says "the next key I press".
	 *
	 * <p>The same shape as Minecraft's own Controls screen, because it is
	 * sitting next to it and there is nothing to gain by being different.
	 */
	private final class KeybindButton extends ButtonWidget {
		private final SettingsState.Row row;

		KeybindButton(SettingsState.Row row, int x, int width) {
			super(x, 0, width, ROW_H, Text.empty(), b -> {
			}, DEFAULT_NARRATION_SUPPLIER);
			this.row = row;
			stopCapture();
		}

		@Override
		public void onPress() {
			beginCapture(this);
		}

		void startCapture() {
			setMessage(Text.literal("> " + key() + " <").formatted(Formatting.YELLOW));
		}

		void stopCapture() {
			setMessage(Text.literal(key()));
		}

		/** Just the combination: the action it runs is drawn beside the button. */
		private String key() {
			return trim(row.choiceLabel(), KEY_W - 10);
		}
	}

	/**
	 * A slider that reports once, when it is let go.
	 *
	 * <p>Sending on every frame of a drag would be a message a pixel, and the
	 * daemon would answer each one with a fresh page — the handle would fight
	 * the mouse. Dragging is local; the wire hears about it at the end.
	 */
	private final class SettingSlider extends SliderWidget {
		private final SettingsState.Row row;
		private double sent;

		SettingSlider(SettingsState.Row row, int x, int y, int width) {
			super(x, y, width, ROW_H, Text.empty(), row.normalised());
			this.row = row;
			this.sent = row.normalised();
			updateMessage();
		}

		private double current() {
			return row.denormalised(value);
		}

		@Override
		protected void updateMessage() {
			String shown = "%".equals(row.unit())
					? Math.round(current() * 100) + "%"
					: String.valueOf(Math.round(current() * 100) / 100.0);
			setMessage(Text.literal(row.label() + ": " + shown));
		}

		@Override
		protected void applyValue() {
			// Local only. onRelease and keyPressed decide when the daemon hears.
		}

		private void publish() {
			if (value == sent) {
				return;
			}
			sent = value;
			connection.settingSet(row.key(), current());
		}

		@Override
		public void onRelease(double mouseX, double mouseY) {
			super.onRelease(mouseX, mouseY);
			publish();
		}

		@Override
		public boolean keyPressed(int keyCode, int scanCode, int modifiers) {
			boolean handled = super.keyPressed(keyCode, scanCode, modifiers);
			if (handled) {
				publish();
			}
			return handled;
		}
	}
}
