package dev.mcshell.render;

import net.minecraft.block.BlockState;
import net.minecraft.client.render.model.BakedModel;
import net.minecraft.client.render.model.BakedQuad;
import net.minecraft.client.render.model.json.ModelOverrideList;
import net.minecraft.client.render.model.json.ModelTransformation;
import net.minecraft.client.texture.Sprite;
import net.minecraft.util.math.Direction;
import net.minecraft.util.math.random.Random;
import org.jetbrains.annotations.Nullable;

import java.util.List;

/**
 * The model an application item renders with: vanilla's, made builtin.
 *
 * <p>This is the whole trick that lets an arbitrary {@code .desktop} PNG be a
 * real Minecraft item. A baked model's quads carry UVs into a texture atlas, and
 * an icon discovered at runtime can never be stitched into one — which is what
 * made this look impossible. But {@code ItemRenderer.renderItem} checks
 * {@code isBuiltin()} first, and a model that says yes skips the baked-quad path
 * entirely for a call into {@code BuiltinModelItemRenderer} holding a live
 * {@code VertexConsumerProvider}. That is arbitrary geometry against an
 * arbitrary texture, and it is how vanilla draws chests, shields and heads.
 *
 * <p>So no atlas, no generated resource pack, and no resource reload when the
 * catalog changes.
 *
 * <p>Everything except {@code isBuiltin} and the quads is delegated to the real
 * baked model of {@code mcshell:app}, which is parented to
 * {@code minecraft:item/generated}. That is deliberate: the display transforms
 * that decide how an item sits in a hand, on the ground and in a GUI come from
 * vanilla's own flat-item model rather than from numbers copied into a JSON file
 * here, so an application is held exactly the way a map or a piece of paper is.
 */
public record AppItemModel(BakedModel delegate) implements BakedModel {
	/** Never consulted: a builtin model's quads are not read by the item renderer. */
	@Override
	public List<BakedQuad> getQuads(@Nullable BlockState state, @Nullable Direction face, Random random) {
		return List.of();
	}

	@Override
	public boolean useAmbientOcclusion() {
		return false;
	}

	@Override
	public boolean hasDepth() {
		return delegate.hasDepth();
	}

	@Override
	public boolean isSideLit() {
		return delegate.isSideLit();
	}

	@Override
	public boolean isBuiltin() {
		return true;
	}

	/** Only used for break particles, which an application item never makes. */
	@Override
	public Sprite getParticleSprite() {
		return delegate.getParticleSprite();
	}

	@Override
	public ModelTransformation getTransformation() {
		return delegate.getTransformation();
	}

	@Override
	public ModelOverrideList getOverrides() {
		return ModelOverrideList.EMPTY;
	}
}
