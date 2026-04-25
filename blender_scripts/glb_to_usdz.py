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
                dst.writestr(entry, src.read(entry.filename), compress_type=zipfile.ZIP_STORED)
    os.replace(tmp_path, path)
    print(f"[Blender] Repacked USDZ as uncompressed ZIP (iOS compatible)")


def verify_usdz(path: str) -> bool:
    """Confirm output is a valid, iOS-compatible USDZ."""
    if not zipfile.is_zipfile(path):
        print(f"[Blender] ERROR: output is not a valid ZIP file: {path}")
        return False

    with zipfile.ZipFile(path, "r") as zf:
        entries = zf.infolist()
        names = [e.filename for e in entries]

        # Must contain at least one USD file
        if not any(n.lower().endswith((".usdc", ".usda", ".usd")) for n in names):
            print(f"[Blender] ERROR: no .usdc/.usda/.usd found in archive. Contents: {names}")
            return False

        # USD file must be the first entry — iOS Quick Look reads entry[0] as scene root
        if not entries[0].filename.lower().endswith((".usdc", ".usda", ".usd")):
            print(f"[Blender] ERROR: first archive entry is not a USD file: {entries[0].filename}")
            return False

        # All entries must use STORE — iOS rejects DEFLATE and shows "No file to preview"
        compressed = [e.filename for e in entries if e.compress_type != zipfile.ZIP_STORED]
        if compressed:
            print(f"[Blender] ERROR: compressed entries found — iOS will reject: {compressed}")
            return False

        print(f"[Blender] USDZ verified OK. Contents: {names}")
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
    import_result = bpy.ops.import_scene.gltf(filepath=input_path)
    if import_result != {"FINISHED"}:
        raise RuntimeError(f"GLB import failed — operator returned: {import_result}")

    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError(
            "GLB import produced no mesh objects — file may be empty, "
            "contain only cameras/lights, or use an unsupported feature."
        )
    print(f"[Blender] Imported {len(mesh_objects)} mesh object(s)")

    # ── Step 4: Prepare meshes ────────────────────────────────────────
    # Guarantee Object Mode — transform_apply and modifier_apply both require it.
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")

    # Make every mesh data-block single-user so transform_apply does not fail
    # on GLB files that use instanced geometry (multiple objects sharing one mesh).
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.make_single_user(object=True, obdata=True)
    bpy.ops.object.select_all(action="DESELECT")

    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        # Bake world-space transforms into vertex positions for correct USD placement.
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # iPhone Quick Look requires triangle-only meshes — quads/ngons are invisible.
        tri_mod = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
        tri_mod.quad_method = "BEAUTY"
        tri_mod.ngon_method = "BEAUTY"
        bpy.ops.object.modifier_apply(modifier=tri_mod.name)

        obj.select_set(False)

    bpy.ops.object.select_all(action="DESELECT")

    # ── Step 5: Export to .usdz ───────────────────────────────────────
    # generate_preview_surface: converts Blender materials to UsdPreviewSurface —
    #   Apple's required PBR shader for correct rendering in iPhone Quick Look.
    # export_textures_mode='NEW': copies texture images into the USDZ archive
    #   so there are no external references iOS cannot resolve.
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

    # ── Step 6: Repack as iOS-compatible uncompressed ZIP ────────────
    if not os.path.exists(output_path):
        raise RuntimeError(
            f"USD export reported FINISHED but output file not found: {output_path}"
        )

    repack_usdz_ios_compatible(output_path)

    # ── Step 7: Validate output ───────────────────────────────────────
    if not verify_usdz(output_path):
        raise RuntimeError(
            f"Output failed iOS compatibility checks (see above). Path: {output_path}"
        )

    print(f"[Blender] Done → {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
