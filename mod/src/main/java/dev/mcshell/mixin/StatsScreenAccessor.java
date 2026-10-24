package dev.mcshell.mixin;

import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.screen.StatsScreen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/**
 * Reaches {@code StatsScreen}'s own parent.
 *
 * <p>Needed because the machine's statistics screen replaces the vanilla one
 * and has to know where it came <em>from</em>. Closing back onto the screen we
 * replaced would be a loop: it is redirected on init, so it would hand us
 * straight back. That is exactly what happened, and it left no way out of the
 * screen at all — Done and Escape both.
 */
@Mixin(StatsScreen.class)
public interface StatsScreenAccessor {
	@Accessor("parent")
	Screen mcshell$parent();
}
