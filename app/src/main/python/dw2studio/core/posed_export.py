"""Export the same skinned rest/animation-zero pose that the VTK viewer displays.

Wavefront OBJ is static: this exports the *evaluated* pose, not the skeleton or
animation clips. This deliberately avoids trimesh's non-skinned glTF scene dump.
"""
from pathlib import Path
import tempfile


def export_evaluated_obj(source, target):
    from vtkmodules.vtkIOImport import vtkGLTFImporter
    from vtkmodules.vtkIOExport import vtkOBJExporter
    from vtkmodules.vtkRenderingCore import vtkRenderWindow, vtkRenderer
    import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
    import vtkmodules.vtkRenderingFreeType  # noqa: F401

    source, target = Path(source).resolve(), Path(target).resolve()
    if source.suffix.lower() not in ('.gltf', '.glb') or target.suffix.lower() != '.obj':
        raise ValueError('Erwartet glTF/GLB als Quelle und OBJ als Ziel.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dw2_pose_') as temp:
        prefix = Path(temp) / 'pose'
        window = vtkRenderWindow()
        window.SetOffScreenRendering(1)
        window.SetSize(320, 320)
        renderer = vtkRenderer()
        window.AddRenderer(renderer)
        importer = vtkGLTFImporter()
        importer.SetFileName(str(source))
        importer.SetRenderWindow(window)
        importer.Update()
        if importer.GetNumberOfAnimations():
            for index in range(importer.GetNumberOfAnimations()):
                importer.DisableAnimation(index)
            importer.EnableAnimation(0)
            importer.UpdateAtTimeValue(0.0)
        window.Render()
        exporter = vtkOBJExporter()
        exporter.SetRenderWindow(window)
        exporter.SetFilePrefix(str(prefix))
        exporter.Write()
        obj = prefix.with_suffix('.obj')
        if not obj.is_file() or obj.stat().st_size < 100:
            raise RuntimeError('VTK konnte die animierte Geometrie nicht als OBJ exportieren.')
        mtl = prefix.with_suffix('.mtl')
        if not mtl.is_file():
            raise RuntimeError('VTK hat keine OBJ-Materialdatei erzeugt.')
        from dw2studio.core.obj_atlas import collapse_obj_textures
        obj_text, mtl_text, atlas = collapse_obj_textures(obj, mtl, Path(temp), target.stem)
        target.write_text(obj_text, encoding='utf-8')
        (target.parent / (target.stem + '.mtl')).write_text(mtl_text, encoding='utf-8')
        atlas.save(target.parent / (target.stem + '_texture.png'))
        window.Finalize()
    return target
