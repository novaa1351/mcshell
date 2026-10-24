package dev.mcshell.mixin;

import net.minecraft.client.gui.screen.option.AccessibilityOptionsScreen;
import net.minecraft.client.gui.widget.DirectionalLayoutWidget;
import net.minecraft.client.gui.widget.Widget;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Redirect;

/**
 * Drops the <i>Accessibility Guide</i> button from the bottom of the screen.
 *
 * <p>Every other options screen puts one button in its footer — Done, centred —
 * and the shell's lane switch sits in the bottom-left corner beside it. This
 * screen is the exception: it builds a two-button row, so the guide landed
 * exactly where the lane switch already was and the two overlapped, each
 * drawing through the other.
 *
 * <p>The button is <b>removed rather than moved</b>. It opens minecraft.net in
 * a browser, which in this shell means a window flying up over the desktop
 * from a settings screen — and the page it opens is a marketing overview of
 * features that are all on the screen behind it. Nothing here is worse for its
 * absence, and the alternative was to shuffle the shell's own button somewhere
 * this one screen keeps it and no other does.
 *
 * <p>Done at the point vanilla <em>adds</em> it rather than by hunting the
 * built screen for a button with the right label. A widget removed afterwards
 * leaves its gap: the footer is a {@code DirectionalLayoutWidget} and its
 * positions are computed once, from its children, in {@code init}. Never
 * adding the guide means Done is the row's only child and comes out centred,
 * exactly as it does on Sound, Video and Controls.
 *
 * <p>Ordinal 0 is the guide and ordinal 1 is Done — read from the bytecode of
 * {@code AccessibilityOptionsScreen.initFooter}, which adds them in that
 * order and calls nothing else on the row.
 */
@Mixin(AccessibilityOptionsScreen.class)
public class AccessibilityOptionsScreenMixin {
	@Redirect(
			method = "initFooter",
			at = @At(
					value = "INVOKE",
					target = "Lnet/minecraft/client/gui/widget/DirectionalLayoutWidget;"
							+ "add(Lnet/minecraft/client/gui/widget/Widget;)"
							+ "Lnet/minecraft/client/gui/widget/Widget;",
					ordinal = 0))
	private Widget mcshell$dropAccessibilityGuide(DirectionalLayoutWidget row, Widget guide) {
		// Built and thrown away. Vanilla pops the return value, so handing the
		// button straight back costs nothing and keeps the redirect honest
		// about what it replaced.
		return guide;
	}
}
