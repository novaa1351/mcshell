package dev.mcshell.mixin;

import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.advancement.AdvancementsScreen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/**
 * Vanilla's advancement screen knows what it was opened from. We need that.
 *
 * <p>Same trap the Statistics screen sprang: the screen is replaced on init,
 * so handing the replacement the screen it replaced makes closing a loop —
 * Done would rebuild the very screen that redirects, forever. The way out is
 * the screen vanilla itself would have gone back to.
 */
@Mixin(AdvancementsScreen.class)
public interface AdvancementsScreenAccessor {
	@Accessor("parent")
	Screen mcshell$parent();
}
