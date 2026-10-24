package dev.mcshell.mixin;

import dev.mcshell.item.AppItem;
import dev.mcshell.render.AppItemModel;
import net.minecraft.client.render.item.ItemRenderer;
import net.minecraft.client.render.model.BakedModel;
import net.minecraft.entity.LivingEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.world.World;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Hands an application item a builtin model, so it can draw its own icon.
 *
 * <p>{@code getModel} is the single choke point for every way an item is drawn:
 * {@code DrawContext.drawItem} calls it for the hotbar and the inventory, and
 * {@code ItemRenderer.renderItem} calls it for a hand and for a dropped stack.
 * One injection here therefore reaches all of them, which is why the icon cannot
 * end up correct in a GUI and wrong in the world.
 *
 * <p>At RETURN rather than HEAD, because what is wrapped is vanilla's own baked
 * model of {@code mcshell:app} — the wrapper keeps its display transforms and
 * only changes the answer to {@code isBuiltin()}.
 */
@Mixin(ItemRenderer.class)
public class ItemRendererMixin {
	/**
	 * One wrapper, reused.
	 *
	 * <p>This runs several times a frame for every visible stack, and a fresh
	 * wrapper per call would be a steady drip of garbage for no reason: the
	 * delegate is the same baked model every time until a resource reload
	 * replaces it, which the identity check below notices.
	 */
	private BakedModel mcshell$wrappedDelegate;
	private BakedModel mcshell$wrapper;

	@Inject(method = "getModel", at = @At("RETURN"), cancellable = true)
	private void mcshell$appModel(ItemStack stack, World world, LivingEntity entity, int seed,
			CallbackInfoReturnable<BakedModel> cir) {
		if (!AppItem.is(stack)) {
			return;
		}
		BakedModel delegate = cir.getReturnValue();
		if (delegate == null) {
			return;
		}
		if (delegate != mcshell$wrappedDelegate) {
			mcshell$wrappedDelegate = delegate;
			mcshell$wrapper = new AppItemModel(delegate);
		}
		cir.setReturnValue(mcshell$wrapper);
	}
}
