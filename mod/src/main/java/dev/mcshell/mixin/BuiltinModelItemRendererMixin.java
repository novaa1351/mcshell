package dev.mcshell.mixin;

import dev.mcshell.item.AppItem;
import dev.mcshell.render.AppItemRenderer;
import net.minecraft.client.render.VertexConsumerProvider;
import net.minecraft.client.render.item.BuiltinModelItemRenderer;
import net.minecraft.client.render.model.json.ModelTransformationMode;
import net.minecraft.client.util.math.MatrixStack;
import net.minecraft.item.ItemStack;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Draws an application item where vanilla draws chests and shields.
 *
 * <p>The other half of {@link dev.mcshell.render.AppItemModel}: having claimed
 * to be builtin, the model is sent here, and here is where an arbitrary texture
 * can finally be used. Cancelled on our own items only — every vanilla builtin
 * goes on down its own path untouched.
 */
@Mixin(BuiltinModelItemRenderer.class)
public class BuiltinModelItemRendererMixin {
	@Inject(method = "render", at = @At("HEAD"), cancellable = true)
	private void mcshell$renderApp(ItemStack stack, ModelTransformationMode mode,
			MatrixStack matrices, VertexConsumerProvider vertexConsumers,
			int light, int overlay, CallbackInfo ci) {
		if (!AppItem.is(stack)) {
			return;
		}
		AppItemRenderer.render(stack, matrices, vertexConsumers, light, overlay);
		ci.cancel();
	}
}
