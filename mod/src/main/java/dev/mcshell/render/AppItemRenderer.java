package dev.mcshell.render;

import dev.mcshell.MCShellClient;
import dev.mcshell.item.AppItem;
import net.minecraft.client.render.RenderLayer;
import net.minecraft.client.render.item.ItemRenderer;
import net.minecraft.client.render.VertexConsumer;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.item.ItemStack;
import net.minecraft.util.Identifier;

/**
 * Draws one application item, wherever Minecraft is drawing items.
 *
 * <p>Reached through {@link AppItemModel}'s builtin branch, so this one method
 * covers every surface at once: the hotbar, the inventory, the hand in first and
 * third person, and a stack lying on the ground. There is no separate GUI path to
 * keep in step with a world path, which is the reason for taking the builtin
 * route rather than special-casing {@code DrawContext}.
 */
public final class AppItemRenderer {
	/** Shown when an application's .desktop names an icon that is not installed. */
	private static final Identifier FALLBACK =
			Identifier.of(MCShellClient.MOD_ID, "textures/item/app.png");

	/**
	 * Model space is the unit cube: {@code ItemRenderer.renderItem} applies the
	 * display transform and then translates by -0.5 on every axis, so 0..1 is
	 * the item, and 0.5 is the plane a flat item lives on.
	 */
	private static final float MIN = 0.0f;
	private static final float MAX = 1.0f;
	private static final float PLANE = 0.5f;

	private AppItemRenderer() {
	}

	public static void render(ItemStack stack, MatrixStack matrices,
			VertexConsumerProvider vertexConsumers, int light, int overlay) {

		Identifier texture = texture(stack);

		// Launching is the one state vanilla has no component for: spawned, no
		// window mapped yet. A faded icon needs real blending, and cutout does
		// not blend — it alpha-tests and writes whatever survives at full
		// opacity — so the layer changes rather than just the vertex colour.
		// getEntityTranslucent disables culling as well, so a fading icon is
		// still two-sided like every other one.
		boolean launching = AppItem.isLaunching(stack);
		int alpha = launching ? 90 : 255;

		// No culling, so one quad is visible from both sides — a flat item seen
		// from behind in third person would otherwise vanish.
		//
		// Cutout rather than translucent, and that is a choice rather than an
		// accident: it alpha-tests instead of blending, which gives an icon hard
		// edges and no sorting to get wrong. Hard edges are also the correct
		// look here — the shell is meant to read as a resource pack, and a
		// smoothly feathered icon is exactly the tell that it is not.
		// Through vanilla's own glint wrapper, so a running application is
		// enchanted in the literal sense: the same second pass over the same
		// scrolling texture that an enchanted sword gets. The builtin branch
		// skips the glint that renderItem applies to baked models, so it has to
		// be asked for here — which is exactly what vanilla's shield does.
		RenderLayer layer = launching
				? RenderLayer.getEntityTranslucent(texture)
				: RenderLayer.getEntityCutoutNoCull(texture);
		VertexConsumer buffer = ItemRenderer.getDirectItemGlintConsumer(
				vertexConsumers, layer, true, stack.hasGlint());
		MatrixStack.Entry entry = matrices.peek();

		// Counter-clockwise from the bottom-left, seen from +Z. V is flipped
		// against Y: model space counts up from the bottom, texture space counts
		// down from the top.
		vertex(buffer, entry, MIN, MIN, 0.0f, 1.0f, light, overlay, alpha);
		vertex(buffer, entry, MAX, MIN, 1.0f, 1.0f, light, overlay, alpha);
		vertex(buffer, entry, MAX, MAX, 1.0f, 0.0f, light, overlay, alpha);
		vertex(buffer, entry, MIN, MAX, 0.0f, 0.0f, light, overlay, alpha);
	}

	private static void vertex(VertexConsumer buffer, MatrixStack.Entry entry,
			float x, float y, float u, float v, int light, int overlay, int alpha) {
		buffer.vertex(entry, x, y, PLANE)
				.color(255, 255, 255, alpha)
				.texture(u, v)
				.overlay(overlay)
				.light(light)
				.normal(entry, 0.0f, 0.0f, 1.0f);
	}

	/**
	 * The application's own icon, or the placeholder tile.
	 *
	 * <p>{@link IconTextures} is the one cache in the mod, so an icon is
	 * uploaded to the GPU once however many places it appears — the hotbar, the
	 * inventory, the catalog and your hand are all this method.
	 */
	private static Identifier texture(ItemStack stack) {
		IconTextures icons = MCShellClient.icons();
		String path = AppItem.iconPath(stack);
		if (icons == null || path == null) {
			return FALLBACK;
		}
		Identifier id = icons.get(path);
		return id == null ? FALLBACK : id;
	}
}
