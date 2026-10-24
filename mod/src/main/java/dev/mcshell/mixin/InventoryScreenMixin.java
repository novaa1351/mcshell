package dev.mcshell.mixin;

import dev.mcshell.screen.InventoryIntegration;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.ingame.InventoryScreen;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Draws the catalog tab behind the survival inventory panel.
 *
 * <p>A mixin only because of the layering, which is the whole look. A creative
 * tab is 32 tall against a panel edge it overlaps by four pixels, and it reads
 * as <em>tucked under</em> the panel because vanilla draws unselected tabs
 * first and the panel over them. Fabric's screen events cannot get in there:
 * {@code beforeRender} is earlier than the darkening pass, so the tab would be
 * dimmed along with the world, and {@code afterRender} is later than the panel,
 * so the tab would sit on top of it and read as the selected page.
 *
 * <p>HEAD of {@code drawBackground} is exactly between the two — after the
 * screen has dimmed the world, before it draws its panel.
 *
 * <p>The click is not here. It belongs to a widget in
 * {@link InventoryIntegration}, which gets the tooltip, the click sound and the
 * narration for free; this only paints.
 */
@Mixin(InventoryScreen.class)
public class InventoryScreenMixin {
	@Inject(method = "drawBackground", at = @At("HEAD"))
	private void mcshell$drawCatalogTab(DrawContext context, float delta, int mouseX, int mouseY,
			CallbackInfo ci) {
		InventoryIntegration.drawCatalogTab(context, (InventoryScreen) (Object) this);
	}
}
