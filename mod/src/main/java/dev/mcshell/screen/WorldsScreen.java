package dev.mcshell.screen;

import com.mojang.blaze3d.systems.RenderSystem;
import dev.mcshell.MCShellClient;
import dev.mcshell.net.DaemonConnection;
import dev.mcshell.net.WorldsState;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.tooltip.Tooltip;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.client.texture.NativeImage;
import net.minecraft.client.texture.NativeImageBackedTexture;
import net.minecraft.screen.ScreenTexts;
import net.minecraft.text.Text;
import net.minecraft.util.Identifier;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The world picker, drawn as Realms' world slots.
 *
 * <p>Realms' configure screen is the one place Minecraft shows worlds as
 * pictures you choose between, so each world is a {@code RealmsWorldSlotButton}
 * — ported rather than reused, because that class reads a Realms server
 * object. Its geometry is read out of the 1.21.1 bytecode: the preview is
 * drawn 74x74 at (3,3) inside the 80x80 {@code widget/slot_frame} sprite, the
 * {@code icon/checkmark} sits at (67,4), the name is centred at (40,66) and a
 * second line at (40,82), and slots stand 98 apart from {@code width/2 - 187}.
 *
 * <p>The tint is Realms' too, and it reads backwards until you see what it
 * means: the <em>active</em> slot is drawn like a pressed button — preview at
 * 0.56, frame at 0.8, a checkmark, and no click — while every slot you could
 * switch to is bright, its frame lighting up under the cursor. Here "active"
 * is the world the next start opens. The one running now says so underneath.
 *
 * <p>The mod decides nothing. A click sends {@code world_choose} and the
 * screen redraws from the daemon's answer; restart sends
 * {@code world_restart} and gets out of the way, because what comes next is
 * the boot screen.
 *
 * <p>A world with no {@code icon.png} — one nobody has played yet — gets the
 * panorama images Realms uses for a slot with no picture.
 */
public final class WorldsScreen extends Screen {
	private static final int TILE = 80;
	private static final int PITCH = 98;
	private static final int IMAGE = 74;
	private static final int INSET = 3;
	private static final int PER_PAGE = 4;
	private static final int ROW_W = TILE + (PER_PAGE - 1) * PITCH;
	private static final int BUTTON_W = 204;
	private static final int BUTTON_H = 20;

	private static final Identifier SLOT_FRAME = Identifier.ofVanilla("widget/slot_frame");
	private static final Identifier CHECKMARK = Identifier.ofVanilla("icon/checkmark");
	private static final Identifier[] PANORAMAS = {
			Identifier.ofVanilla("textures/gui/title/background/panorama_0.png"),
			Identifier.ofVanilla("textures/gui/title/background/panorama_2.png"),
			Identifier.ofVanilla("textures/gui/title/background/panorama_3.png"),
	};

	private final DaemonConnection connection;
	private final Screen parent;
	private final Map<String, Identifier> previews = new HashMap<>();
	private final Set<String> failed = new HashSet<>();
	private WorldsState shown;
	private int page;

	public WorldsScreen(DaemonConnection connection, Screen parent) {
		super(Text.translatable("mcshell.worlds.title"));
		this.connection = connection;
		this.parent = parent;
	}

	@Override
	protected void init() {
		if (shown == null) {
			connection.worldsQuery();
		}
		shown = connection.worlds();
		List<WorldsState.World> worlds = shown.worlds();
		int pages = Math.max(1, (worlds.size() + PER_PAGE - 1) / PER_PAGE);
		page = Math.min(page, pages - 1);

		int left = width / 2 - ROW_W / 2;
		int top = height / 2 - TILE / 2 - 12;
		int first = page * PER_PAGE;
		for (int i = first; i < Math.min(worlds.size(), first + PER_PAGE); i++) {
			addDrawableChild(new Tile(worlds.get(i), i, left + (i - first) * PITCH, top));
		}

		if (pages > 1) {
			int arrowY = top + TILE / 2 - BUTTON_H / 2;
			addDrawableChild(ButtonWidget.builder(Text.literal("<"), b -> turn(-1))
					.dimensions(left - 24, arrowY, 20, BUTTON_H).build()).active = page > 0;
			addDrawableChild(ButtonWidget.builder(Text.literal(">"), b -> turn(1))
					.dimensions(left + ROW_W + 4, arrowY, 20, BUTTON_H).build()).active = page < pages - 1;
		}

		ButtonWidget restart = ButtonWidget.builder(
						Text.translatable("mcshell.worlds.restart", shown.chosen()), b -> restart())
				.dimensions(width / 2 - BUTTON_W / 2, height - 51, BUTTON_W, BUTTON_H).build();
		restart.active = shown.pending();
		addDrawableChild(restart);
		addDrawableChild(ButtonWidget.builder(ScreenTexts.DONE, b -> close())
				.dimensions(width / 2 - BUTTON_W / 2, height - 27, BUTTON_W, BUTTON_H).build());
	}

	@Override
	public void tick() {
		// The daemon's answer lands on the socket thread; rebuild when it does,
		// so the checkmark and the restart button follow a click.
		if (connection.worlds() != shown) {
			clearAndInit();
		}
	}

	private void turn(int delta) {
		page += delta;
		clearAndInit();
	}

	private void restart() {
		connection.worldRestart();
		if (client != null) {
			client.setScreen(null);
		}
	}

	@Override
	public void render(DrawContext context, int mouseX, int mouseY, float delta) {
		super.render(context, mouseX, mouseY, delta);
		context.drawCenteredTextWithShadow(textRenderer, title, width / 2, 20, 0xFFFFFF);
		if (shown != null && shown.worlds().isEmpty()) {
			context.drawCenteredTextWithShadow(textRenderer, Text.translatable("mcshell.worlds.none"),
					width / 2, height / 2 - 4, 0xA0A0A0);
		}
	}

	/** The world's own icon.png at full size, or null for the panorama. */
	private Identifier preview(WorldsState.World world) {
		if (world.icon().isEmpty()) {
			return null;
		}
		String key = world.icon() + "#" + world.iconVersion();
		if (failed.contains(key)) {
			return null;
		}
		Identifier cached = previews.get(key);
		if (cached != null) {
			return cached;
		}
		try (InputStream in = Files.newInputStream(Path.of(world.icon()))) {
			NativeImage image = NativeImage.read(in);
			Identifier id = Identifier.of(MCShellClient.MOD_ID,
					"world/" + Integer.toUnsignedString(key.hashCode(), 16));
			MinecraftClient.getInstance().getTextureManager()
					.registerTexture(id, new NativeImageBackedTexture(image));
			previews.put(key, id);
			return id;
		} catch (Exception e) {
			MCShellClient.LOG.warn("could not load world preview {}: {}", world.icon(), e.toString());
			failed.add(key);
			return null;
		}
	}

	@Override
	public void removed() {
		MinecraftClient client = MinecraftClient.getInstance();
		for (Identifier id : previews.values()) {
			client.getTextureManager().destroyTexture(id);
		}
		previews.clear();
		super.removed();
	}

	@Override
	public void close() {
		if (client != null) {
			client.setScreen(parent);
		}
	}

	@Override
	public boolean shouldPause() {
		return false;
	}

	/** One world slot. A real button, so the click sound, focus and narration are vanilla's. */
	private final class Tile extends ButtonWidget {
		private final WorldsState.World world;
		private final int index;

		Tile(WorldsState.World world, int index, int x, int y) {
			super(x, y, TILE, TILE, Text.literal(world.name()),
					b -> connection.worldChoose(world.name()), DEFAULT_NARRATION_SUPPLIER);
			this.world = world;
			this.index = index;
			boolean chosen = world.name().equals(shown.chosen());
			boolean running = world.name().equals(shown.running());
			// The chosen slot is Realms' active one: nothing to switch to.
			this.active = !chosen;
			setTooltip(Tooltip.of(Text.translatable(running ? "mcshell.worlds.tooltip.running"
					: chosen ? "mcshell.worlds.tooltip.chosen" : "mcshell.worlds.tooltip.choose")));
		}

		@Override
		protected void renderWidget(DrawContext context, int mouseX, int mouseY, float delta) {
			int x = getX();
			int y = getY();
			boolean chosen = world.name().equals(shown.chosen());
			boolean running = world.name().equals(shown.running());

			Identifier image = preview(world);
			if (image == null) {
				image = PANORAMAS[index % PANORAMAS.length];
			}
			if (chosen) {
				context.setShaderColor(0.56F, 0.56F, 0.56F, 1.0F);
			}
			context.drawTexture(image, x + INSET, y + INSET, 0.0F, 0.0F, IMAGE, IMAGE, IMAGE, IMAGE);

			if (isSelected() && !chosen) {
				context.setShaderColor(1.0F, 1.0F, 1.0F, 1.0F);
			} else if (chosen) {
				context.setShaderColor(0.8F, 0.8F, 0.8F, 1.0F);
			} else {
				context.setShaderColor(0.56F, 0.56F, 0.56F, 1.0F);
			}
			context.drawGuiTexture(SLOT_FRAME, x, y, TILE, TILE);
			context.setShaderColor(1.0F, 1.0F, 1.0F, 1.0F);

			if (chosen) {
				RenderSystem.enableBlend();
				context.drawGuiTexture(CHECKMARK, x + 67, y + 4, 9, 8);
				RenderSystem.disableBlend();
			}

			var font = MinecraftClient.getInstance().textRenderer;
			String name = font.trimToWidth(world.name(), IMAGE);
			context.drawCenteredTextWithShadow(font, name, x + 40, y + 66, -1);
			Text status = running ? Text.translatable("mcshell.worlds.in_use")
					: chosen ? Text.translatable("mcshell.worlds.next") : null;
			if (status != null) {
				context.drawCenteredTextWithShadow(font, status, x + 40, y + 82, -1);
			}
		}
	}
}
