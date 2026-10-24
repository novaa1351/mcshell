package dev.mcshell.mixin;

import dev.mcshell.screen.PowerIntegration;
import dev.mcshell.screen.WorldsIntegration;
import net.minecraft.client.gui.screen.GameMenuScreen;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.client.gui.widget.ButtonWidget;
import net.minecraft.text.Text;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.Redirect;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

import java.net.URI;

/**
 * <i>Save and Quit to Title</i> opens the machine's power menu instead.
 *
 * <p>There is no title screen to go back to. The world is the shell, so
 * quitting it leaves a logged-in session with nothing on the screen — the one
 * button on the pause menu whose vanilla meaning the shell cannot honour. It
 * keeps its wording, like <i>Open to LAN</i> and <i>Statistics</i>: it is
 * already the button about leaving, and a renamed one is a tell.
 *
 * <p>Hooked at {@code disconnect()} rather than by finding the button, because
 * that is where every route to the title screen ends up and it is a method
 * with a name rather than a lambda inside a layout. Cancelling at HEAD costs
 * nothing: its first act is to read whether the world is singleplayer.
 *
 * <p>Returning from the power menu re-shows this screen, and {@code setScreen}
 * re-runs {@code init} — so the button that vanilla disabled on the way in is
 * rebuilt and live again, with nothing here to put back.
 */
@Mixin(GameMenuScreen.class)
public class GameMenuScreenMixin {
	@Inject(method = "disconnect", at = @At("HEAD"), cancellable = true)
	private void mcshell$openPowerMenu(CallbackInfo ci) {
		// Only if the shell is actually there to answer. With no daemon the
		// vanilla button is the lesser of two bad outcomes: a title screen is
		// recoverable, a menu whose every button does nothing is not.
		if (PowerIntegration.open((Screen) (Object) this)) {
			ci.cancel();
		}
	}

	@Shadow
	private static ButtonWidget createUrlButton(Screen screen, Text text, URI uri) {
		throw new AssertionError();
	}

	/**
	 * <i>Give Feedback</i> becomes <i>Worlds...</i>, the world picker.
	 *
	 * <p>In singleplayer the pause menu builds two link buttons side by side
	 * in {@code addFeedbackAndBugsButtons}, and both open minecraft.net — in
	 * this shell, a browser window over the desktop. The first is replaced;
	 * <i>Report Bugs</i> is left where it is.
	 *
	 * <p>Renamed, unlike <i>Statistics</i> and <i>Open to LAN</i>: those kept
	 * their words because they are close to what now sits behind them, and
	 * "feedback" says nothing about worlds.
	 *
	 * <p>Redirected at the call rather than by finding the button afterwards,
	 * so the grid lays out the replacement exactly where the original went.
	 * With no daemon the vanilla link is built instead.
	 */
	@Redirect(method = "addFeedbackAndBugsButtons",
			at = @At(value = "INVOKE",
					target = "Lnet/minecraft/client/gui/screen/GameMenuScreen;createUrlButton(Lnet/minecraft/client/gui/screen/Screen;Lnet/minecraft/text/Text;Ljava/net/URI;)Lnet/minecraft/client/gui/widget/ButtonWidget;",
					ordinal = 0))
	private static ButtonWidget mcshell$worldsButton(Screen parent, Text text, URI uri) {
		if (!WorldsIntegration.available()) {
			return createUrlButton(parent, text, uri);
		}
		// 98 is GameMenuScreen.NORMAL_BUTTON_WIDTH, what createUrlButton uses.
		return ButtonWidget.builder(Text.translatable("mcshell.worlds.button"),
				button -> WorldsIntegration.open(parent)).width(98).build();
	}
}
