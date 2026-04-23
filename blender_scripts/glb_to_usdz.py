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
        if arg == "--input":
            input_path = args[i + 1]
        elif arg == "--output":
            output_path = args[i + 1]
    if not input_path or not output_path:
        raise ValueError("Both --input and --output are required.")
    return input_path, output_path


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

    # ── Step 4: Export directly to .usdz (native in Blender 5.0) ─────
    # Note: export_textures_mode valid values in Blender 5.0: 'KEEP', 'PRESERVE', 'NEW'
    print(f"[Blender] Exporting USDZ: {output_path}")
    result = bpy.ops.wm.usd_export(
        filepath=output_path,
        export_materials=True,
        export_textures_mode='NEW',
        generate_preview_surface=True,
        overwrite_textures=True,
    )
    print(f"[Blender] Export result: {result}")

    if not os.path.exists(output_path):
        raise RuntimeError(f"USD export returned {result} but file not found: {output_path}")

    print(f"[Blender] Done → {output_path} ({os.path.getsize(output_path)} bytes)")


if __name__ == "__main__":
    main()
