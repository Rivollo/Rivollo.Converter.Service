"""
Blender headless script: GLB → USDZ conversion.

Confirmed working on Blender 5.0.1 (snap) on Ubuntu.
Blender 5.0 supports native .usdz export — no manual zip workaround needed.

Called via:
  blender --background --python app/services/blender_scripts/glb_to_usdz.py \
          -- --input /path/to/model.glb --output /path/to/model.usdz
"""

import os
import sys
import zipfile
import bpy


def parse_args():
    """Parse args after '--' separator (Blender's custom arg convention)."""
    argv = sys.argv
    if "--" not in argv:
        raise ValueError(
            "Usage: blender --background --python glb_to_usdz.py "
            "-- --input <glb_path> --output <usdz_path>"
        )
    args = argv[argv.index("--") + 1:]
    input_path, output_path = None, None
    for i, arg in enumerate(args):
        if arg == "--input" and i + 1 < len(args):
            input_path = args[i + 1]
        elif arg == "--output" and i + 1 < len(args):
            output_path = args[i + 1]
    if not input_path or not output_path:
        raise ValueError("Both --input and --output are required.")
    return input_path, output_path


def repack_usdz_ios_compatible(path: str) -> None:
    """
    Repack the USDZ as an uncompressed ZIP (ZIP_STORED).
    iOS Quick Look strictly requires STORE compression — DEFLATE causes "No file to preview".
    The primary .usdc/.usda file must also be the first entry in the archive.
    """
    tmp_path = path + ".repack.tmp"
    with zipfile.ZipFile(path, "r") as src:
        entries = src.infolist()
        # Primary USD file must be first — iOS Quick Look reads the first entry as the scene root
        entries.sort(key=lambda e: (
            0 if e.filename.lower().endswith((".usdc", ".usda", ".usd")) else 1,
            e.filename,
        ))
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_STORED) as dst:
            for entry in entries:
                dst.writestr(entry, src.read(entry.filename))
    os.replace(tmp_path, path)
    print(f"[Blender] Repacked USDZ as uncompressed ZIP (iOS compatible)")


def verify_usdz(path: str) -> bool:
    """Confirm output is a valid, iOS-compatible USDZ."""
    if not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path, "r") as zf:
        entries = zf.infolist()
        names = [e.filename for e in entries]
        has_usd = any(n.lower().endswith((".usdc", ".usda", ".usd")) for n in names)
        if not has_usd:
            return False
        compressed = [e.filename for e in entries if e.compress_type != zipfile.ZIP_STORED]
        if compressed:
            print(f"[Blender] WARNING: compressed entries found (iOS will reject): {compressed}")
        print(f"[Blender] USDZ contents: {names}")
        return True


def main():
    input_path, output_path = parse_args()

    # ── Step 1: Clear default scene ───────────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # ── Step 2: Enable GLB import addon (required in headless Blender) ─
    import addon_utils
    addon_utils.enable("io_scene_gltf2", default_set=False)

    # ── Step 3: Import GLB ────────────────────────────────────────────
    print(f"[Blender] Importing GLB: {input_path}")
    bpy.ops.import_scene.gltf(filepath=input_path)

    # ── Step 4: Prepare meshes ────────────────────────────────────────
    # Apply transforms so geometry is baked correctly into USD space.
    # Triangulate: iPhone Quick Look requires triangle-only meshes.
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        tri_mod = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
        tri_mod.quad_method = "BEAUTY"
        tri_mod.ngon_method = "BEAUTY"
        bpy.ops.object.modifier_apply(modifier=tri_mod.name)
        obj.select_set(False)

    bpy.ops.object.select_all(action="DESELECT")

    # ── Step 5: Export to .usdz ───────────────────────────────────────
    # generate_preview_surface: converts Blender materials to UsdPreviewSurface,
    # Apple's standard PBR shader — required for correct rendering in iPhone Quick Look.
    # export_uvmaps + export_normals: ensures textures and shading transfer correctly.
    # export_textures + export_textures_mode='NEW': embeds textures inside the ZIP.
    print(f"[Blender] Exporting USDZ: {output_path}")
    result = bpy.ops.wm.usd_export(
        filepath=output_path,
        export_materials=True,
        generate_preview_surface=True,
        export_textures=True,
        export_textures_mode="NEW",
        export_uvmaps=True,
        export_normals=True,
        export_mesh_colors=False,
        use_instancing=False,
        root_prim_path="/Root",
    )
    print(f"[Blender] Export result: {result}")

    # ── Step 6: Repack as iOS-compatible uncompressed ZIP ────────────
    if not os.path.exists(output_path):
        raise RuntimeError(f"USD export returned {result} but file not found: {output_path}")

    repack_usdz_ios_compatible(output_path)

    # ── Step 7: Validate output ───────────────────────────────────────
    if not verify_usdz(output_path):
        raise RuntimeError(
            f"Output is not a valid USDZ archive (expected ZIP with .usdc inside): {output_path}"
        )

    print(f"[Blender] Done → {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
