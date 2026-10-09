"""Entrada e saida de cena no Blender: importar asset, achar o rig, exportar."""

from __future__ import annotations

from pathlib import Path

import bpy
import numpy as np

ASSET_EXTENSIONS = (".fbx", ".glb", ".gltf", ".blend", ".obj")


def call_op(op, **kwargs):
    """Chama um operador passando so as propriedades que esta versao do Blender conhece."""
    known = {p.identifier for p in op.get_rna_type().properties}
    return op(**{k: v for k, v in kwargs.items() if k in known})


def import_asset(path: Path, link_textures: bool = True) -> dict:
    """Abre o asset numa cena limpa e liga as texturas que estiverem na pasta dele.

    Devolve ``{"notes": [...], "unused_files": [...]}`` sobre as texturas. Passe
    ``link_textures=False`` para arquivos que nao sao a fonte de um asset (ex.: o
    .blend de um resultado, cuja pasta tem outras imagens).
    """
    from . import textures

    _load(path)
    if not link_textures:
        return {"notes": [], "unused_files": []}
    return textures.link_textures(path.parent)


def _load(path: Path) -> None:
    if path.suffix.lower() == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
        return
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_into_scene(path)


def import_into_scene(path: Path) -> list:
    """Importa um arquivo para a cena atual, sem limpar nada. Devolve os objetos novos."""
    ext = path.suffix.lower()
    before = set(bpy.data.objects)
    if ext == ".fbx":
        try:
            bpy.ops.wm.fbx_import(filepath=str(path))
        except (AttributeError, RuntimeError):
            bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    elif ext == ".blend":
        with bpy.data.libraries.load(str(path), link=False) as (source, target):
            target.objects = source.objects
        for obj in target.objects:
            if obj is not None:
                bpy.context.scene.collection.objects.link(obj)
    else:
        raise ValueError(f"Formato não suportado: {ext} (aceitos: {', '.join(ASSET_EXTENSIONS)})")
    return [o for o in bpy.data.objects if o not in before]


def meshes_of(arm_obj) -> list:
    out = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        skinned = any(m.type == "ARMATURE" and m.object == arm_obj for m in obj.modifiers)
        if skinned or obj.parent == arm_obj:
            out.append(obj)
    return out


def find_rig() -> tuple[object | None, list]:
    """Armature principal (a que deforma mais malhas) e as malhas ligadas a ela."""
    armatures = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    if not armatures:
        return None, [o for o in bpy.context.scene.objects if o.type == "MESH"]
    best = max(armatures, key=lambda a: (len(meshes_of(a)), len(a.data.bones)))
    return best, meshes_of(best)


def world_bbox(objs) -> tuple[np.ndarray, np.ndarray] | None:
    pts = []
    for obj in objs:
        mw = np.array(obj.matrix_world)
        corners = np.array([[*c, 1.0] for c in obj.bound_box])
        pts.append((corners @ mw.T)[:, :3])
    if not pts:
        return None
    pts = np.concatenate(pts)
    return pts.min(axis=0), pts.max(axis=0)


def export_glb(path: Path, active_action_only: bool = False, nla_tracks: bool = False) -> None:
    """``nla_tracks``: cada faixa NLA sai como um clipe, com o nome e a duracao dela."""
    kwargs = dict(
        filepath=str(path),
        export_format="GLB",
        export_animations=True,
        export_skins=True,
        export_yup=True,
        export_cameras=False,
        export_lights=False,
    )
    if active_action_only:
        kwargs["export_animation_mode"] = "ACTIVE_ACTIONS"
    if nla_tracks:
        kwargs["export_animation_mode"] = "NLA_TRACKS"
        kwargs["export_frame_range"] = False  # cada clipe tem o seu tamanho, nao o da cena
    call_op(bpy.ops.export_scene.gltf, **kwargs)


def export_fbx(path: Path, nla_strips: bool = False, **options) -> None:
    """``nla_strips``: cada faixa NLA sai como uma tomada (take) do FBX. ``options`` vai para o exportador."""
    types = {"ARMATURE", "MESH"}
    # Um acessorio fica preso ao osso por um Empty. Sem o Empty no arquivo, a malha dele sai
    # solta na raiz, seguindo a mao so por animacao propria, o que nem toda engine aproveita.
    if any(o.type == "EMPTY" and o.parent_type == "BONE" for o in bpy.context.scene.objects):
        types.add("EMPTY")
    call_op(
        bpy.ops.export_scene.fbx,
        filepath=str(path),
        use_selection=False,
        object_types=types,
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=nla_strips,
        bake_anim_use_all_bones=True,
        bake_anim_simplify_factor=0.0,
        path_mode="COPY",
        embed_textures=True,
        **options,
    )


def save_blend(path: Path) -> None:
    try:
        bpy.ops.file.pack_all()
    except RuntimeError:
        pass  # textura ausente no disco: salva sem empacotar essa
    bpy.ops.wm.save_as_mainfile(filepath=str(path), compress=True)
