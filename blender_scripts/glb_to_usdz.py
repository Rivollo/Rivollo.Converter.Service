"""
Blender headless script: GLB → USDZ conversion.
Works on Mac (Quick Look) and iPhone (iOS Quick Look / AR).

Strategy:
  - Export directly to .usdz — Blender natively embeds textures inside the ZIP.
  - Repack the ZIP with explicit STORE compression (iOS rejects DEFLATE).
  - Verify the archive has the correct structure before finishing.

Called via:
  blender --background --python glb_to_usdz.py \
          -- --input /path/to/model.glb --output /path/to/model.usdz
"""

import os
import sys
import zipfile
import bpy


def parse_args():
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


def repack_as_store(usdz_path: str) -> None:
    """
    Repack the USDZ ZIP with STORE compression on every entry.

    iOS Quick Look requires:
      - ZIP_STORED compression — DEFLATE causes 'No file to preview'.
      - Primary .usdc as the FIRST entry in the archive.
    """
    tmp_path = usdz_path + ".tmp"

    with zipfile.ZipFile(usdz_path, "r") as src:
        entries = src.infolist()

        print(f"[Blender] Original USDZ contents: {[e.filename for e in entries]}")

        # .usdc must be first entry — iOS reads entry[0] as the scene root
        entries.sort(key=lambda e: (
            0 if e.filename.lower().endswith((".usdc", ".usda", ".usd")) else 1,
            e.filename,
        ))

        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_STORED) as dst:
            for entry in entries:
                # compress_type on writestr overrides ZipInfo.compress_type —
                # without this, ZipInfo carries the original DEFLATE and STORE is ignored.
                dst.writestr(entry, src.read(entry.filename), compress_type=zipfile.ZIP_STORED)

    os.replace(tmp_path, usdz_path)
    print(f"[Blender] Repacked as STORE compression (iOS compatible)")


def verify_usdz(path: str) -> bool:
    """Verify the USDZ is valid for Mac and iPhone."""
    if not zipfile.is_zipfile(path):
        print(f"[Blender] ERROR: not a valid ZIP: {path}")
        return False

    with zipfile.ZipFile(path, "r") as zf:
        entries = zf.infolist()
        names = [e.filename for e in entries]

        # Must contain a USD file
        usd_names = [n for n in names if n.lower().endswith((".usdc", ".usda", ".usd"))]
        if not usd_names:
            print(f"[Blender] ERROR: no USD file in archive. Contents: {names}")
            return False

        # USD file must be first entry
        if not entries[0].filename.lower().endswith((".usdc", ".usda", ".usd")):
            print(f"[Blender] ERROR: first entry is not a USD file: {entries[0].filename}")
            return False

        # Must have textures inside the ZIP — no textures = grey/blank on iPhone
        texture_exts = (".png", ".jpg", ".jpeg")
        texture_names = [n for n in names if n.lower().endswith(texture_exts)]
        if not texture_names:
            print(f"[Blender] WARNING: no texture files found in archive — model may appear grey")

        # All entries must be STORE — iOS rejects DEFLATE
        compressed = [e.filename for e in entries if e.compress_type != zipfile.ZIP_STORED]
        if compressed:
            print(f"[Blender] ERROR: compressed entries — iPhone will reject: {compressed}")
            return False

        print(f"[Blender] USDZ verified OK. Contents: {names}")
        return True


def main():
    input_path, output_path = parse_args()

    # ── Step 1: Clear default scene ───────────────────────────────────
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # ── Step 2: Enable GLB import addon ──────────────────────────────
    import addon_utils
    addon_utils.enable("io_scene_gltf2", default_set=False)

    # ── Step 3: Import GLB ────────────────────────────────────────────
    print(f"[Blender] Importing GLB: {input_path}")
    import_result = bpy.ops.import_scene.gltf(filepath=input_path)
    if import_result != {"FINISHED"}:
        raise RuntimeError(f"GLB import failed — operator returned: {import_result}")

    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError(
            "GLB import produced no mesh objects — file may be empty "
            "or contain only cameras/lights."
        )
    print(f"[Blender] Imported {len(mesh_objects)} mesh object(s)")

    # ── Step 4: Prepare meshes ────────────────────────────────────────
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")

    # make_single_user prevents transform_apply crash on instanced meshes
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.make_single_user(object=True, obdata=True)
    bpy.ops.object.select_all(action="DESELECT")

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Bake transforms into vertex positions for correct USD placement
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # iPhone Quick Look requires triangle-only meshes
        tri_mod = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
        tri_mod.quad_method = "BEAUTY"
        tri_mod.ngon_method = "BEAUTY"
        bpy.ops.object.modifier_apply(modifier=tri_mod.name)

        obj.select_set(False)

    bpy.ops.object.select_all(action="DESELECT")

    # ── Step 5: Export directly to .usdz ─────────────────────────────
    # Blender's native .usdz export embeds textures inside the ZIP.
    # generate_preview_surface converts materials to UsdPreviewSurface —
    # the only shader iOS Quick Look understands.
    print(f"[Blender] Exporting USDZ: {output_path}")
    export_result = bpy.ops.wm.usd_export(
        filepath=output_path,
        export_materials=True,
        generate_preview_surface=True,
        export_textures_mode="NEW",
        root_prim_path="/Root",
    )
    print(f"[Blender] Export result: {export_result}")

    if export_result != {"FINISHED"}:
        raise RuntimeError(f"USD export failed — operator returned: {export_result}")

    if not os.path.exists(output_path):
        raise RuntimeError(f"Export reported FINISHED but file not found: {output_path}")

    # ── Step 6: Repack as STORE compression ───────────────────────────
    # Blender may use DEFLATE — iOS rejects any compression other than STORE.
    repack_as_store(output_path)

    # ── Step 7: Validate ─────────────────────────────────────────────
    if not verify_usdz(output_path):
        raise RuntimeError(f"USDZ failed validation. Path: {output_path}")

    print(f"[Blender] Done → {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
