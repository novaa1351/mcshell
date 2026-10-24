package dev.mcshell.render;

import dev.mcshell.MCShellClient;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.texture.NativeImage;
import net.minecraft.client.texture.NativeImageBackedTexture;
import net.minecraft.util.Identifier;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * Loads application icons from the filesystem and caches them as GPU textures,
 * keyed on path.
 *
 * <p>Icons arrive from the daemon as plain paths — same machine, so there is no
 * reason to base64 them through the socket. They are scaled to 16x16 with
 * nearest-neighbour so they read as Minecraft items rather than as smoothly
 * resampled desktop icons.
 *
 * <p>Not thread safe: every method must be called from the render thread,
 * because uploading a texture touches GL state.
 */
public final class IconTextures {
	/** Vanilla item size. Anything larger stops looking like an item. */
	private static final int SIZE = 16;

	private final Map<String, Identifier> cache = new HashMap<>();
	/** Paths that failed once. Retrying every frame would be a disaster. */
	private final Set<String> failed = new HashSet<>();

	/**
	 * The texture for an icon path, or null if it cannot be loaded.
	 */
	public Identifier get(String iconPath) {
		if (iconPath == null || iconPath.isEmpty() || failed.contains(iconPath)) {
			return null;
		}
		Identifier cached = cache.get(iconPath);
		if (cached != null) {
			return cached;
		}

		try {
			Identifier id = load(iconPath);
			cache.put(iconPath, id);
			return id;
		} catch (Exception e) {
			// Includes unreadable files, unsupported formats (SVG, which the
			// daemon only sends when no raster icon exists), and GL failures.
			MCShellClient.LOG.warn("could not load icon {}: {}", iconPath, e.toString());
			failed.add(iconPath);
			return null;
		}
	}

	private Identifier load(String iconPath) throws Exception {
		NativeImage image;
		try (InputStream in = Files.newInputStream(Path.of(iconPath))) {
			NativeImage source = NativeImage.read(in);
			if (source.getWidth() == SIZE && source.getHeight() == SIZE) {
				// Already item-sized; the texture takes ownership of it.
				image = source;
			} else {
				try (source) {
					image = downscale(source);
				}
			}
		}

		Identifier id = Identifier.of(MCShellClient.MOD_ID, "icon/" + hash(iconPath));
		MinecraftClient.getInstance().getTextureManager()
				.registerTexture(id, new NativeImageBackedTexture(image));
		return id;
	}

	/** Nearest-neighbour, deliberately: bilinear makes desktop icons look mushy at 16px. */
	private static NativeImage downscale(NativeImage source) {
		NativeImage out = new NativeImage(NativeImage.Format.RGBA, SIZE, SIZE, false);
		int sw = source.getWidth();
		int sh = source.getHeight();
		for (int y = 0; y < SIZE; y++) {
			int sy = Math.min(sh - 1, y * sh / SIZE);
			for (int x = 0; x < SIZE; x++) {
				int sx = Math.min(sw - 1, x * sw / SIZE);
				out.setColor(x, y, source.getColor(sx, sy));
			}
		}
		return out;
	}

	/** Icon paths contain characters an Identifier forbids, so key on a digest. */
	private static String hash(String path) {
		try {
			MessageDigest md = MessageDigest.getInstance("SHA-1");
			byte[] digest = md.digest(path.getBytes(java.nio.charset.StandardCharsets.UTF_8));
			StringBuilder sb = new StringBuilder(digest.length * 2);
			for (byte b : digest) {
				sb.append(Character.forDigit((b >> 4) & 0xF, 16));
				sb.append(Character.forDigit(b & 0xF, 16));
			}
			return sb.toString();
		} catch (NoSuchAlgorithmException e) {
			throw new IllegalStateException("SHA-1 is required by the JLS", e);
		}
	}

	/** Drop every cached texture, e.g. when the daemon reconnects with new paths. */
	public void clear() {
		MinecraftClient client = MinecraftClient.getInstance();
		for (Identifier id : cache.values()) {
			client.getTextureManager().destroyTexture(id);
		}
		cache.clear();
		failed.clear();
	}
}
