package dev.mcshell.mixin;

import dev.mcshell.item.AppItem;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.player.PlayerEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Q does not throw applications away.
 *
 * <p>Dragging one out of the hotbar in the inventory screen unassigns the slot,
 * and that is deliberate enough to mean it. A single keypress with the world in
 * front of you is not: Q would silently take an application off the hotbar while
 * you were looking somewhere else, and the slot it lands in is wherever the item
 * happened to fall.
 *
 * <p>Real items are unaffected — this refuses only when the held stack is an
 * application, so Q still throws wood.
 */
@Mixin(ClientPlayerEntity.class)
public class ClientPlayerEntityMixin {
	@Inject(method = "dropSelectedItem", at = @At("HEAD"), cancellable = true)
	private void mcshell$keepApplications(boolean entireStack, CallbackInfoReturnable<Boolean> cir) {
		PlayerEntity self = (PlayerEntity) (Object) this;
		if (AppItem.is(self.getMainHandStack())) {
			cir.setReturnValue(false);
		}
	}
}
