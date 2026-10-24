package dev.mcshell.mixin;

import dev.mcshell.hud.BatteryBar;
import dev.mcshell.hud.Clock;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.hud.InGameHud;
import net.minecraft.client.render.RenderTickCounter;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Hands the XP bar over to the battery.
 *
 * <p>Both halves are cancelled at HEAD and redrawn, rather than having their
 * values redirected. The bar could have been done either way; the number could
 * not, because vanilla builds it as {@code i + ""} and "80%" is not an int.
 * Doing both the same way keeps the two in one place.
 *
 * <p>Cancelled only when there is a battery to draw. On a machine without one
 * these return false and vanilla's own experience bar runs untouched, which is
 * the right answer for a desktop: no gauge is better than a made-up one.
 *
 * <p>The clock is added rather than swapped in: it is the one HUD element the
 * shell draws that Minecraft has no equivalent of, so there is nothing to
 * cancel. At {@code TAIL} of {@code render}, which is after the whole HUD —
 * a line of text at the top of the screen has nothing to be behind.
 *
 * <p>{@code renderExperienceLevel} is a layer of the HUD's own drawer and is
 * called every frame, with the level test inside it — so cancelling at HEAD
 * draws the percentage even at level 0, which vanilla would skip.
 * {@code renderExperienceBar} is called from {@code renderMainHud} under
 * {@code shouldRenderExperience()}, so the battery follows the same rules the
 * XP bar always did: gone in creative, gone under F1, replaced by the jump bar
 * on a horse.
 */
@Mixin(InGameHud.class)
public class InGameHudMixin {
	@Inject(method = "renderExperienceBar", at = @At("HEAD"), cancellable = true)
	private void mcshell$batteryBar(DrawContext context, int x, CallbackInfo ci) {
		if (BatteryBar.drawBar(context, x)) {
			ci.cancel();
		}
	}

	@Inject(method = "render", at = @At("TAIL"))
	private void mcshell$clock(DrawContext context, RenderTickCounter tickCounter,
			CallbackInfo ci) {
		Clock.draw(context);
	}

	@Inject(method = "renderExperienceLevel", at = @At("HEAD"), cancellable = true)
	private void mcshell$batteryLevel(DrawContext context, RenderTickCounter tickCounter,
			CallbackInfo ci) {
		if (BatteryBar.drawLevel(context)) {
			ci.cancel();
		}
	}
}
