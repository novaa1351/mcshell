package dev.mcshell.screen;

import dev.mcshell.net.DaemonConnection;
import dev.mcshell.net.DirState;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;
import net.minecraft.util.Identifier;
import net.minecraft.util.math.MathHelper;
import com.mojang.blaze3d.systems.RenderSystem;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The Advancements screen, showing directories instead of achievements.
 *
 * <p>Minecraft's advancement window is already a tree: nodes on a grid, gold
 * frames for what has been reached and grey for what has not, branches drawn
 * between a parent and its children, all of it panned around behind a tiled
 * stone background. A filesystem is that shape. So the window is kept — the
 * texture, the geometry, the frames, the two-pass connector lines, the drag
 * to pan — and only the contents are replaced.
 *
 * <p>The one real difference from vanilla is that the tree is not known in
 * advance. An advancement tree arrives whole from the server; a filesystem is
 * discovered a directory at a time, so nothing is under the home directory
 * until it is clicked. One button does both halves of that: a directory that
 * is shut opens, one that is open shuts. There is nothing for a second button
 * to mean, since only an open branch can be closed.
 *
 * <p>Files are drawn beside the directories, with an icon for what they are —
 * a directory full of documents that draws as an empty one is a worse picture
 * than none. They are leaves and nothing else. Nothing opens a file, because
 * nothing here could decide what opening one means.
 *
 * <p>A gold frame therefore means <i>expanded</i> and a grey one <i>not</i>,
 * which is as close to vanilla's own meaning as this screen gets: gold is the
 * part of the tree you have opened up.
 *
 * <p>Nothing is cached. Every expansion is a fresh question to the daemon,
 * because a directory listing stops being true the moment somebody saves a
 * file, and a file viewer that shows yesterday's directory is worse than one
 * that is slow.
 */
public final class FileTreeScreen extends Screen {
	// -- vanilla AdvancementsScreen geometry --------------------------------
	/** The window in the texture, and the smallest one this screen will draw. */
	private static final int SRC_W = 252;
	private static final int SRC_H = 140;
	private static final int SRC_PAGE_W = 234;
	private static final int SRC_PAGE_H = 113;
	private static final int PAGE_X = 9;
	private static final int PAGE_Y = 18;
	/** What the frame costs the page, kept at vanilla's own proportions. */
	private static final int FRAME_W = SRC_W - SRC_PAGE_W;
	private static final int FRAME_H = SRC_H - SRC_PAGE_H;
	/**
	 * The nine-slice corner: large enough to carry the rounded bevel whole, so
	 * only flat border is ever repeated.
	 */
	private static final int CORNER = 32;
	/** Screen left around the window. */
	private static final int MARGIN = 16;
	private static final int TITLE_X = 8;
	private static final int TITLE_Y = 6;
	private static final int TITLE_COLOR = 4210752;

	/** Vanilla's grid pitch, from AdvancementPositioner. */
	private static final int COL_W = 28;
	private static final int ROW_H = 27;
	/** The frame is 26x26 and sits three pixels right of the node's own origin. */
	private static final int FRAME = 26;
	private static final int FRAME_DX = 3;
	private static final int ICON_DX = 8;
	private static final int ICON_DY = 5;

	private static final Identifier WINDOW =
			Identifier.ofVanilla("textures/gui/advancements/window.png");
	private static final Identifier STONE =
			Identifier.ofVanilla("textures/gui/advancements/backgrounds/stone.png");
	private static final Identifier FRAME_EXPANDED =
			Identifier.ofVanilla("advancements/task_frame_obtained");
	private static final Identifier FRAME_COLLAPSED =
			Identifier.ofVanilla("advancements/task_frame_unobtained");
	private static final Identifier FOLDER =
			Identifier.of("mcshell", "textures/gui/folder.png");

	/**
	 * One icon per kind of file the daemon names, and a plain page for the
	 * rest. The mapping is the mod's because the textures are: the daemon
	 * decides what a file <i>is</i>, this decides what that looks like.
	 */
	private static final Map<String, Identifier> ICONS = icons(
			"file", "text", "doc", "pdf", "sheet", "slides", "image",
			"audio", "video", "code", "config", "archive", "font", "binary");

	private static Map<String, Identifier> icons(String... kinds) {
		Map<String, Identifier> out = new HashMap<>();
		for (String kind : kinds) {
			out.put(kind, Identifier.of("mcshell", "textures/gui/file/" + kind + ".png"));
		}
		return Map.copyOf(out);
	}

	/**
	 * How many children one expansion shows. The daemon's own cap, repeated
	 * here only so the paging nodes can say what they step by.
	 */
	private static final int PAGE = 20;

	/**
	 * How far the mouse may move between press and release and still count as
	 * a click. Dragging is how the tree is panned, and a pan that ends over a
	 * folder must not open it.
	 */
	private static final double CLICK_SLOP = 3.0;

	private final DaemonConnection connection;
	private final Screen parent;

	private final Node root = new Node(null, "", "…", "dir");
	private boolean centred;

	/**
	 * The window is grown to the screen rather than left at vanilla's 252x140.
	 *
	 * <p>A directory tree is not an advancement tree: it is browsed rather than
	 * admired, and four rows of eight is not enough to see where you are. The
	 * frame is nine-sliced instead of scaled, so every pixel on this screen —
	 * border, folder, text — stays at the same size as every other pixel in the
	 * game. Scaling the window would have been one line and would have made the
	 * chrome twice the size of its own contents, which is the tell.
	 */
	private int windowW = SRC_W;
	private int windowH = SRC_H;

	private int pageW() {
		return windowW - FRAME_W;
	}

	private int pageH() {
		return windowH - FRAME_H;
	}

	private double originX;
	private double originY;
	private int minPanX;
	private int maxPanX;
	private int minPanY;
	private int maxPanY;

	private double pressX;
	private double pressY;
	private boolean dragged;

	public FileTreeScreen(DaemonConnection connection, Screen parent) {
		super(Text.translatable("gui.advancements"));
		this.connection = connection;
		this.parent = parent;
	}

	@Override
	protected void init() {
		windowW = Math.max(SRC_W, width - 2 * MARGIN);
		windowH = Math.max(SRC_H, height - 2 * MARGIN);
		if (centred) {
			// Re-clamp: a resize changes what "as far as it will go" means.
			move(0, 0);
		}
		if (root.path.isEmpty() && !root.loading) {
			// An empty path means "wherever home is" — the daemon knows, and
			// the answer comes back resolved, so the root has a real path from
			// the first reply onwards.
			root.loading = true;
			connection.dirQuery("", 0, PAGE);
		}
	}

	@Override
	public void close() {
		// The screen this one replaced, never that screen itself: vanilla's is
		// redirected on init, so going back to it would bounce straight here
		// again and there would be no way out.
		if (client != null) {
			client.setScreen(parent);
		}
	}

	// -- the tree ----------------------------------------------------------

	/** One directory on screen. Children are null until it has been expanded. */
	private static final class Node {
		final Node parent;
		final int depth;
		String path;
		String name;
		/** {@code "dir"}, a file kind, or empty for a paging step. */
		final String kind;

		List<Node> children;
		int total;
		int hidden;
		int offset;
		boolean loading;
		String error = "";

		/** A step to another page of a crowded directory, rather than a directory. */
		final boolean paging;
		final int pageTo;

		int x;
		int y;
		float row;

		Node(Node parent, String path, String name, String kind) {
			this(parent, path, name, kind, false, 0);
		}

		Node(Node parent, String path, String name, String kind, boolean paging, int pageTo) {
			this.parent = parent;
			this.depth = parent == null ? 0 : parent.depth + 1;
			this.path = path;
			this.name = name;
			this.kind = kind;
			this.paging = paging;
			this.pageTo = pageTo;
		}

		boolean isDir() {
			return "dir".equals(kind);
		}

		boolean expanded() {
			return children != null;
		}
	}

	/** Take whatever the daemon has answered and hang it on the tree. */
	private void drain() {
		DirState listing;
		boolean changed = false;
		while ((listing = connection.nextDir()) != null) {
			changed |= adopt(listing);
		}
		if (changed) {
			layout();
		}
	}

	private boolean adopt(DirState listing) {
		Node node = find(listing);
		if (node == null) {
			return false;
		}
		node.loading = false;
		node.path = listing.path();
		if (node == root) {
			node.name = listing.name();
		}
		node.error = listing.error();
		node.total = listing.total();
		node.hidden = listing.hidden();
		node.offset = listing.offset();

		if (!node.error.isEmpty()) {
			// Unreadable is a leaf, not an empty directory. Left collapsed so
			// the frame keeps saying so and the tooltip can say why.
			node.children = null;
			return true;
		}

		List<Node> children = new ArrayList<>();
		if (listing.offset() > 0) {
			children.add(new Node(node, node.path, "… previous " + PAGE, "",
					true, Math.max(0, listing.offset() - PAGE)));
		}
		for (DirState.Entry entry : listing.entries()) {
			children.add(new Node(node, entry.path(), entry.name(), entry.kind()));
		}
		int shown = listing.offset() + listing.entries().size();
		if (shown < listing.total()) {
			children.add(new Node(node, node.path,
					"… " + (listing.total() - shown) + " more", "", true, shown));
		}
		node.children = children;
		return true;
	}

	/**
	 * Which node a listing belongs to.
	 *
	 * <p>Matched on the path it asked about, preferring one still waiting: the
	 * same directory is listed again to step to its next page, and the answer
	 * belongs to whoever asked.
	 */
	private Node find(DirState listing) {
		if (root.path.isEmpty() && root.loading) {
			return root;
		}
		Node fallback = null;
		for (Node node : all()) {
			if (!node.path.equals(listing.path())) {
				continue;
			}
			if (node.loading) {
				return node;
			}
			if (fallback == null) {
				fallback = node;
			}
		}
		return fallback;
	}

	private List<Node> all() {
		List<Node> out = new ArrayList<>();
		collect(root, out);
		return out;
	}

	private static void collect(Node node, List<Node> out) {
		out.add(node);
		if (node.children != null) {
			for (Node child : node.children) {
				collect(child, out);
			}
		}
	}

	// -- layout ------------------------------------------------------------

	private int cursor;

	/**
	 * Place every visible node on vanilla's grid.
	 *
	 * <p>A column per level of depth, leaves stacked a row apart, and a parent
	 * hung halfway down its own children — the tidy-tree shape vanilla's own
	 * positioner produces, arrived at the short way because our trees are a
	 * few dozen nodes rather than a whole advancement file.
	 *
	 * <p>Rows are fractional so a parent of two sits between them instead of
	 * on top of one. Columns are never shared between depths, so nothing can
	 * collide.
	 */
	private void layout() {
		// Expanding a node re-rows everything below it. Hold the node the eye
		// is on still, or the branch you just opened jumps out from under the
		// cursor that opened it.
		Node anchor = anchorNode;
		int before = anchor == null ? 0 : anchor.y;

		cursor = 0;
		place(root);

		minPanX = Integer.MAX_VALUE;
		maxPanX = Integer.MIN_VALUE;
		minPanY = Integer.MAX_VALUE;
		maxPanY = Integer.MIN_VALUE;
		for (Node node : all()) {
			minPanX = Math.min(minPanX, node.x);
			maxPanX = Math.max(maxPanX, node.x + COL_W);
			minPanY = Math.min(minPanY, node.y);
			maxPanY = Math.max(maxPanY, node.y + ROW_H);
		}

		if (!centred) {
			originX = pageW() / 2.0 - (maxPanX + minPanX) / 2.0;
			originY = pageH() / 2.0 - (maxPanY + minPanY) / 2.0;
			centred = true;
		} else if (anchor != null) {
			originY += before - anchor.y;
		}
		anchorNode = null;
		move(0, 0);
	}

	private Node anchorNode;

	private float place(Node node) {
		node.x = node.depth * COL_W;
		List<Node> children = node.children;
		if (children == null || children.isEmpty()) {
			node.row = cursor++;
		} else {
			float first = Float.NaN;
			float last = 0;
			for (Node child : children) {
				last = place(child);
				if (Float.isNaN(first)) {
					first = last;
				}
			}
			node.row = (first + last) / 2.0F;
		}
		node.y = Math.round(node.row * ROW_H);
		return node.row;
	}

	/** Vanilla's clamp: pan only along an axis the tree actually overflows. */
	private void move(double dx, double dy) {
		if (maxPanX - minPanX > pageW()) {
			originX = MathHelper.clamp(originX + dx, -(maxPanX - pageW()), -minPanX);
		} else {
			originX = pageW() / 2.0 - (maxPanX + minPanX) / 2.0;
		}
		if (maxPanY - minPanY > pageH()) {
			originY = MathHelper.clamp(originY + dy, -(maxPanY - pageH()), -minPanY);
		} else {
			originY = pageH() / 2.0 - (maxPanY + minPanY) / 2.0;
		}
	}

	// -- rendering ---------------------------------------------------------

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		drain();
		super.render(context, mouseX, mouseY, delta);

		int x = windowX();
		int y = windowY();
		drawTree(context, x, y);
		drawWindow(context, x, y);
		drawNodeTooltip(context, mouseX, mouseY, x, y);
	}

	private int windowX() {
		return (width - windowW) / 2;
	}

	private int windowY() {
		return (height - windowH) / 2;
	}

	private void drawTree(DrawContext context, int x, int y) {
		context.enableScissor(x + PAGE_X, y + PAGE_Y,
				x + PAGE_X + pageW(), y + PAGE_Y + pageH());
		MatrixStack matrices = context.getMatrices();
		matrices.push();
		matrices.translate(x + PAGE_X, y + PAGE_Y, 0.0F);

		RenderSystem.enableBlend();
		int ox = MathHelper.floor(originX);
		int oy = MathHelper.floor(originY);
		int tileX = ox % 16;
		int tileY = oy % 16;
		int tileCols = (pageW() + 15) / 16 + 1;
		int tileRows = (pageH() + 15) / 16 + 1;
		for (int col = -1; col <= tileCols; col++) {
			for (int row = -1; row <= tileRows; row++) {
				context.drawTexture(STONE, tileX + 16 * col, tileY + 16 * row,
						0.0F, 0.0F, 16, 16, 16, 16);
			}
		}

		// Twice, exactly as vanilla: a black pass that widens every line into
		// its own border, then the white one down the middle of it.
		drawLines(context, root, ox, oy, true);
		drawLines(context, root, ox, oy, false);
		for (Node node : all()) {
			drawNode(context, node, ox, oy);
		}
		RenderSystem.disableBlend();

		matrices.pop();
		context.disableScissor();
	}

	private void drawLines(DrawContext context, Node node, int ox, int oy, boolean border) {
		if (node.children != null) {
			for (Node child : node.children) {
				int i = ox + node.x + 13;
				int j = ox + node.x + FRAME + 4;
				int k = oy + node.y + 13;
				int l = ox + child.x + 13;
				int m = oy + child.y + 13;
				int colour = border ? 0xFF000000 : 0xFFFFFFFF;
				if (border) {
					context.drawHorizontalLine(j, i, k - 1, colour);
					context.drawHorizontalLine(j + 1, i, k, colour);
					context.drawHorizontalLine(j, i, k + 1, colour);
					context.drawHorizontalLine(l, j - 1, m - 1, colour);
					context.drawHorizontalLine(l, j - 1, m, colour);
					context.drawHorizontalLine(l, j - 1, m + 1, colour);
					context.drawVerticalLine(j - 1, m, k, colour);
					context.drawVerticalLine(j + 1, m, k, colour);
				} else {
					context.drawHorizontalLine(j, i, k, colour);
					context.drawHorizontalLine(l, j, m, colour);
					context.drawVerticalLine(j, m, k, colour);
				}
			}
			for (Node child : node.children) {
				drawLines(context, child, ox, oy, border);
			}
		}
	}

	private void drawNode(DrawContext context, Node node, int ox, int oy) {
		Identifier frame = node.expanded() ? FRAME_EXPANDED : FRAME_COLLAPSED;
		context.drawGuiTexture(frame, ox + node.x + FRAME_DX, oy + node.y, FRAME, FRAME);
		Identifier icon = iconFor(node);
		if (icon != null) {
			context.drawTexture(icon, ox + node.x + ICON_DX, oy + node.y + ICON_DY,
					0.0F, 0.0F, 16, 16, 16, 16);
		}
	}

	/**
	 * A paging step gets an empty frame, on purpose: it is a control, not a
	 * thing on the disk, and any icon would claim it was one.
	 */
	private static Identifier iconFor(Node node) {
		if (node.paging) {
			return null;
		}
		if (node.isDir()) {
			return FOLDER;
		}
		return ICONS.getOrDefault(node.kind, ICONS.get("file"));
	}

	/**
	 * Vanilla's frame, nine-sliced to whatever size the screen allows.
	 *
	 * <p>The four corners are drawn whole and the four edges repeated between
	 * them. The border is a flat bevel rather than a pattern, so a repeat has
	 * no seam to find — checked against a composite of the texture before this
	 * was written, not assumed.
	 */
	private void drawWindow(DrawContext context, int x, int y) {
		int w = windowW;
		int h = windowH;
		context.drawTexture(WINDOW, x, y, 0, 0, CORNER, CORNER);
		context.drawTexture(WINDOW, x + w - CORNER, y, SRC_W - CORNER, 0, CORNER, CORNER);
		context.drawTexture(WINDOW, x, y + h - CORNER, 0, SRC_H - CORNER, CORNER, CORNER);
		context.drawTexture(WINDOW, x + w - CORNER, y + h - CORNER,
				SRC_W - CORNER, SRC_H - CORNER, CORNER, CORNER);

		int gapW = w - 2 * CORNER;
		int stepW = SRC_W - 2 * CORNER;
		for (int dx = 0; dx < gapW; dx += stepW) {
			int piece = Math.min(stepW, gapW - dx);
			context.drawTexture(WINDOW, x + CORNER + dx, y, CORNER, 0, piece, CORNER);
			context.drawTexture(WINDOW, x + CORNER + dx, y + h - CORNER,
					CORNER, SRC_H - CORNER, piece, CORNER);
		}

		int gapH = h - 2 * CORNER;
		int stepH = SRC_H - 2 * CORNER;
		for (int dy = 0; dy < gapH; dy += stepH) {
			int piece = Math.min(stepH, gapH - dy);
			context.drawTexture(WINDOW, x, y + CORNER + dy, 0, CORNER, CORNER, piece);
			context.drawTexture(WINDOW, x + w - CORNER, y + CORNER + dy,
					SRC_W - CORNER, CORNER, CORNER, piece);
		}

		String title = root.path.isEmpty() ? "…" : root.path;
		context.drawText(textRenderer, Text.literal(title),
				x + TITLE_X, y + TITLE_Y, TITLE_COLOR, false);
	}

	private void drawNodeTooltip(DrawContext context, int mouseX, int mouseY, int x, int y) {
		Node hovered = nodeAt(mouseX, mouseY, x, y);
		if (hovered == null) {
			return;
		}
		List<Text> lines = new ArrayList<>();
		lines.add(Text.literal(hovered.name));
		if (!hovered.error.isEmpty()) {
			lines.add(Text.literal(hovered.error).formatted(Formatting.RED));
		} else if (hovered.isDir() && hovered.expanded() && hovered.hidden > 0) {
			// Dotted directories are left out — dozens of them in a home
			// directory, and they would bury what anybody came looking for on
			// the very first click. Counted rather than silently dropped.
			lines.add(Text.literal(hovered.hidden + " hidden").formatted(Formatting.DARK_GRAY));
		}
		context.drawTooltip(textRenderer, lines, mouseX, mouseY);
	}

	/** Which node the cursor is over, in screen coordinates. */
	private Node nodeAt(int mouseX, int mouseY, int x, int y) {
		int left = x + PAGE_X;
		int top = y + PAGE_Y;
		if (mouseX < left || mouseX >= left + pageW() || mouseY < top || mouseY >= top + pageH()) {
			return null;
		}
		int ox = left + MathHelper.floor(originX);
		int oy = top + MathHelper.floor(originY);
		// Backwards, so the node drawn last is the one picked when two overlap.
		List<Node> nodes = all();
		for (int i = nodes.size() - 1; i >= 0; i--) {
			Node node = nodes.get(i);
			int nx = ox + node.x + FRAME_DX;
			int ny = oy + node.y;
			if (mouseX >= nx && mouseX < nx + FRAME && mouseY >= ny && mouseY < ny + FRAME) {
				return node;
			}
		}
		return null;
	}

	// -- input -------------------------------------------------------------

	@Override
	public boolean mouseClicked(double mouseX, double mouseY, int button) {
		if (button == 0) {
			pressX = mouseX;
			pressY = mouseY;
			dragged = false;
			return true;
		}
		return super.mouseClicked(mouseX, mouseY, button);
	}

	@Override
	public boolean mouseDragged(double mouseX, double mouseY, int button, double dx, double dy) {
		if (button != 0) {
			return super.mouseDragged(mouseX, mouseY, button, dx, dy);
		}
		if (Math.abs(mouseX - pressX) > CLICK_SLOP || Math.abs(mouseY - pressY) > CLICK_SLOP) {
			dragged = true;
		}
		move(dx, dy);
		return true;
	}

	@Override
	public boolean mouseReleased(double mouseX, double mouseY, int button) {
		if (button == 0 && !dragged) {
			Node node = nodeAt((int) mouseX, (int) mouseY, windowX(), windowY());
			if (node != null) {
				toggle(node);
				return true;
			}
		}
		return super.mouseReleased(mouseX, mouseY, button);
	}

	@Override
	public boolean mouseScrolled(double mouseX, double mouseY, double horizontal, double vertical) {
		move(0, vertical * 16.0);
		return true;
	}

	/**
	 * One button, both directions: shut opens, open shuts.
	 *
	 * <p>There is nothing a second button could add. Only an open branch can
	 * be closed, so the two gestures can never be asked for in the same state,
	 * and whichever one applies is the only thing a click could sensibly mean.
	 */
	private void toggle(Node node) {
		if (node.loading) {
			return;
		}
		if (node.paging) {
			// A step through a crowded directory: the page moves under the
			// parent, rather than a new branch growing off the step itself.
			Node owner = node.parent;
			if (owner == null) {
				return;
			}
			owner.loading = true;
			anchorNode = owner;
			connection.dirQuery(owner.path, node.pageTo, PAGE);
			return;
		}
		if (!node.isDir()) {
			// A file is a leaf. Nothing here could decide what opening one
			// means, and this screen is not the place that would.
			return;
		}
		if (node.expanded()) {
			anchorNode = node;
			node.children = null;
			node.offset = 0;
			layout();
			return;
		}
		node.loading = true;
		anchorNode = node;
		connection.dirQuery(node.path, 0, PAGE);
	}

	@Override
	public boolean shouldPause() {
		return false;
	}
}
