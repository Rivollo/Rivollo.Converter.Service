"""
Blender headless script: GLB → USDZ conversion.
Works on Mac (Quick Look) and iPhone (iOS Quick Look / AR).

Strategy:
  - Export to .usdc so Blender writes textures as real files on disk.
  - Manually pack .usdc + all textures into a USDZ ZIP with STORE compression.
  - This guarantees textures are INSIDE the archive — required for iPhone.
  - Mac also reads textures from inside the ZIP, so both platforms work.

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


def build_usdz(stage_dir: str, usdz_path: str) -> None:
    """
    Pack everything in stage_dir into a USDZ ZIP.

    USDZ requirements (Mac + iPhone):
      - ZIP with STORE compression only — no DEFLATE.
      - Primary .usdc must be the FIRST entry in the archive.
      - Texture paths inside ZIP must match what .usdc references (relative paths).
    """
    all_files = []
    for root, _, files in os.walk(stage_dir):
        for f in files:
            full_path = os.path.join(root, f)
            arc_name = os.path.relpath(full_path, stage_dir).replace(os.sep, "/")
            all_files.append((full_path, arc_name))

    if not all_files:
        raise RuntimeError(f"Nothing to pack — staging directory is empty: {stage_dir}")

    # .usdc must be first — both Mac and iPhone Quick Look read entry[0] as scene root
    all_files.sort(key=lambda x: (
        0 if x[1].lower().endswith((".usdc", ".usda", ".usd")) else 1,
        x[1],
    ))

    print(f"[Blender] Packing into USDZ: {[x[1] for x in all_files]}")

    with zipfile.ZipFile(usdz_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for full_path, arc_name in all_files:
            zf.write(full_path, arc_name, compress_type=zipfile.ZIP_STORED)

    print(f"[Blender] USDZ written: {usdz_path} ({os.path.getsize(usdz_path)} bytes)")


def verify_usdz(path: str) -> bool:
    """Verify the USDZ is valid for Mac and iPhone."""
    if not zipfile.is_zipfile(path):
        print(f"[Blender] ERROR: not a valid ZIP: {path}")
        return False

    with zipfile.ZipFile(path, "r") as zf:
        entries = zf.infolist()
        names = [e.filename for e in entries]

        usd_names = [n for n in names if n.lower().endswith((".usdc", ".usda", ".usd"))]
        if not usd_names:
            print(f"[Blender] ERROR: no USD file in archive. Contents: {names}")
            return False

        if not entries[0].filename.lower().endswith((".usdc", ".usda", ".usd")):
            print(f"[Blender] ERROR: first entry is not a USD file: {entries[0].filename}")
            return False

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

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.make_single_user(object=True, obdata=True)
    bpy.ops.object.select_all(action="DESELECT")

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

    # ── Step 5: Export to .usdc in a staging folder ───────────────────
    # Blender writes model.usdc + textures/ folder on disk.
    # We then manually pack both into the USDZ ZIP (Step 6).
    stage_dir = output_path + ".stage"
    os.makedirs(stage_dir, exist_ok=True)
    usdc_path = os.path.join(stage_dir, "model.usdc")

    print(f"[Blender] Exporting USDC to: {stage_dir}")
    export_result = bpy.ops.wm.usd_export(
        filepath=usdc_path,
        export_materials=True,
        generate_preview_surface=True,
        export_textures_mode="NEW",
        root_prim_path="/Root",
    )
    print(f"[Blender] Export result: {export_result}")

    if export_result != {"FINISHED"}:
        raise RuntimeError(f"USD export failed — operator returned: {export_result}")

    if not os.path.exists(usdc_path):
        raise RuntimeError(f"model.usdc not found after export in: {stage_dir}")

    staged = []
    for root, _, files in os.walk(stage_dir):
        for f in files:
            staged.append(os.path.relpath(os.path.join(root, f), stage_dir))
    print(f"[Blender] Staged files (usdc + textures): {staged}")

    # ── Step 6: Pack usdc + textures into USDZ ZIP ───────────────────
    build_usdz(stage_dir, output_path)

    if not os.path.exists(output_path):
        raise RuntimeError(f"USDZ not created at: {output_path}")

    # ── Step 7: Validate ─────────────────────────────────────────────
    if not verify_usdz(output_path):
        raise RuntimeError(f"USDZ failed validation. Path: {output_path}")

    print(f"[Blender] Done → {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
