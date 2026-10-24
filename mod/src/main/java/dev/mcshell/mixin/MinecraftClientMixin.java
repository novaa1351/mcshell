package dev.mcshell.mixin;

import dev.mcshell.item.AppGestures;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;
import org.jetbrains.annotations.Nullable;

/**
 * The world's four mouse buttons, when an application is in hand.
 *
 * <p>Hooked here rather than on {@code Item.use} because these are the four
 * funnels every click passes through however the player is pointing. Right
 * clicking a block and right clicking the air take different routes into
 * {@code Item}, and only one of them is {@code use}; taking them at the
 * {@code MinecraftClient} level means the gesture works the same whether you
 * are looking at the platform, at the void, or at nothing in particular.
 *
 * <p>Every injection is a no-op unless the held stack is an application, so
 * vanilla mining, placing and attacking are untouched.
 */
@Mixin(MinecraftClient.class)
public class MinecraftClientMixin {
	@Shadow
	@Nullable
	public ClientPlayerEntity player;

	/** Right-click: focus or launch, and with sneak, launch another. */
	@Inject(method = "doItemUse", at = @At("HEAD"), cancellable = true)
	private void mcshell$useApplication(CallbackInfo ci) {
		if (player != null && AppGestures.use(player, player.isSneaking())) {
			ci.cancel();
		}
	}

	/** Left-click: focus, then cycle that application's windows. */
	@Inject(method = "doAttack", at = @At("HEAD"), cancellable = true)
	private void mcshell$cycleApplication(CallbackInfoReturnable<Boolean> cir) {
		if (player != null && AppGestures.attack(player)) {
			// False: nothing was swung at, so vanilla should not start a
			// block-breaking animation on whatever is under the crosshair.
			cir.setReturnValue(false);
		}
	}

	/**
	 * And therefore no mining while holding one.
	 *
	 * <p>Not a separate decision — left-click means cycle now, and this is the
	 * held-down half of the same button. Without it a held left-click would go
	 * on breaking the platform underneath the cycling.
	 */
	@Inject(method = "handleBlockBreaking", at = @At("HEAD"), cancellable = true)
	private void mcshell$noMiningWithApplications(boolean breaking, CallbackInfo ci) {
		if (player != null && AppGestures.holdingApp(player)) {
			ci.cancel();
		}
	}

	/** Shift+middle-click: close a window. Plain middle-click still picks. */
	@Inject(method = "doItemPick", at = @At("HEAD"), cancellable = true)
	private void mcshell$closeWindow(CallbackInfo ci) {
		if (player != null && AppGestures.close(player, player.isSneaking())) {
			ci.cancel();
		}
	}
}
