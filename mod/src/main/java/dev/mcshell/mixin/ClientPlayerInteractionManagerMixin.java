package dev.mcshell.mixin;

import dev.mcshell.item.AppClicks;
import net.minecraft.client.network.ClientPlayerInteractionManager;
import net.minecraft.entity.player.PlayerEntity;
import net.minecraft.screen.slot.SlotActionType;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Keeps an application stack whole.
 *
 * <p>{@code clickSlot} is the single funnel every inventory click passes
 * through, whichever screen is open, so the rule in {@link AppClicks} only has
 * to be written once. Cancelled before the click is predicted locally or sent,
 * which is what stops the split appearing for a frame and then snapping back.
 */
@Mixin(ClientPlayerInteractionManager.class)
public class ClientPlayerInteractionManagerMixin {
	@Inject(method = "clickSlot", at = @At("HEAD"), cancellable = true)
	private void mcshell$keepApplicationsWhole(int syncId, int slotId, int button,
			SlotActionType actionType, PlayerEntity player, CallbackInfo ci) {
		if (player.currentScreenHandler.syncId == syncId
				&& AppClicks.refuse(player.currentScreenHandler, slotId, button, actionType)) {
			ci.cancel();
		}
	}
}
