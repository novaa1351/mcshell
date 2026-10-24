package dev.mcshell.mixin;

import net.minecraft.client.gui.screen.ingame.HandledScreen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/**
 * Reads where a container screen actually drew its panel.
 *
 * <p>{@code HandledScreen.x/y} are protected with no getter, and they are not
 * simply centred: the inventory shifts sideways when the recipe book opens. The
 * catalog button has to sit on the panel's corner, so it needs the real value
 * rather than a recomputed guess that drifts the moment the player toggles the
 * recipe book.
 *
 * <p>An accessor, not an injection — it reads two ints and changes no vanilla
 * behaviour. This is rendering geometry, not a decision; decisions belong to the
 * daemon.
 */
@Mixin(HandledScreen.class)
public interface HandledScreenAccessor {
	@Accessor("x")
	int mcshell$getX();

	@Accessor("y")
	int mcshell$getY();

	@Accessor("backgroundWidth")
	int mcshell$getBackgroundWidth();

	@Accessor("backgroundHeight")
	int mcshell$getBackgroundHeight();
}
