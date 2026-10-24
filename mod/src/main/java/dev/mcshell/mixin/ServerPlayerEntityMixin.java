package dev.mcshell.mixin;

import dev.mcshell.item.AppItem;
import net.minecraft.entity.ItemEntity;
import net.minecraft.item.ItemStack;
import net.minecraft.server.network.ServerPlayerEntity;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * No application is ever dropped into the world, by any route.
 *
 * <p>The clicks that would drop one are refused before they leave the client
 * ({@link dev.mcshell.item.AppClicks}, and {@code ClientPlayerEntityMixin} for Q
 * in the world). This is the backstop behind them. Every way vanilla puts a
 * player's item on the ground ends here on the integrated server — read out of
 * the 1.21.1 bytecode: a click outside the window, Q and Ctrl+Q over a slot,
 * closing a screen with something on the cursor and nowhere to put it, and
 * death without {@code keepInventory}. So a route the client rules missed
 * still cannot leave an application lying on the platform.
 *
 * <p>Refused by returning null, which vanilla already returns for an empty
 * stack, so every caller handles it. The stack is simply not dropped: the
 * hotbar is derived from the daemon's state, and an application the player
 * let go of is one whose slot is already unassigned — the same outcome as
 * carrying it up into storage.
 */
@Mixin(ServerPlayerEntity.class)
public class ServerPlayerEntityMixin {
	@Inject(method = "dropItem(Lnet/minecraft/item/ItemStack;ZZ)Lnet/minecraft/entity/ItemEntity;",
			at = @At("HEAD"), cancellable = true)
	private void mcshell$neverDropApplications(ItemStack stack, boolean throwRandomly,
			boolean retainOwnership, CallbackInfoReturnable<ItemEntity> cir) {
		if (AppItem.is(stack)) {
			cir.setReturnValue(null);
		}
	}
}
