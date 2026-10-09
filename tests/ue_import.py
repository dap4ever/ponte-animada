"""Roda dentro da Unreal (commandlet pythonscript), num projeto de rascunho: importa arquivos e
descreve o que entrou. Quem chama e o tests/check_unreal.py --engine.

O pedido vem num JSON apontado por PONTE_UE_JOB:

    {"report": "<saida.json>", "steps": [{"do": "import", "file": "<fbx>", "dest": "/Game/x", "skeleton": "<asset>"?}]}

Com "skeleton", o arquivo entra num esqueleto que ja existe (o SK_Mannequin), em vez de criar o dele.
"""

import json
import os
import traceback

import unreal

job = json.load(open(os.environ["PONTE_UE_JOB"], encoding="utf-8"))
report = {"engine": unreal.SystemLibrary.get_engine_version(), "steps": []}
POSE = unreal.AnimPoseExtensions


def attempt(row, key, fn):
    try:
        row[key] = fn()
    except Exception as exc:  # a API muda entre versoes: registra e segue
        row.setdefault("errors", {})[key] = repr(exc)


def transform(t):
    q = t.rotation
    return {"loc": [round(v, 5) for v in (t.translation.x, t.translation.y, t.translation.z)], "quat_xyzw": [round(v, 6) for v in (q.x, q.y, q.z, q.w)], "scale": [round(v, 5) for v in (t.scale3d.x, t.scale3d.y, t.scale3d.z)]}


def skeleton_info(skeleton):
    pose = POSE.get_reference_pose(skeleton)
    names = [str(n) for n in POSE.get_bone_names(pose)]
    return {"names": names, "first": [{"name": n, "local": transform(POSE.get_bone_pose(pose, n, unreal.AnimPoseSpaces.LOCAL))} for n in names[:4]]}


def describe(dest):
    rows = []
    for path in unreal.EditorAssetLibrary.list_assets(dest, recursive=True, include_folder=False):
        asset = unreal.EditorAssetLibrary.load_asset(path)
        row = {"path": str(path), "class": asset.get_class().get_name() if asset else None}
        if isinstance(asset, unreal.SkeletalMesh):
            attempt(row, "skeleton", lambda: asset.get_editor_property("skeleton").get_name())
        elif isinstance(asset, unreal.Skeleton):
            attempt(row, "skeleton_info", lambda: skeleton_info(asset))
        elif isinstance(asset, unreal.AnimSequence):
            attempt(row, "skeleton", lambda: asset.get_skeleton().get_name())
            attempt(row, "frames", lambda: unreal.AnimationLibrary.get_num_frames(asset))
        rows.append(row)
    return rows


def do_import(step):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", step["file"])
    task.set_editor_property("destination_path", step["dest"])
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    if step.get("skeleton"):
        skeleton = unreal.load_asset(step["skeleton"])
        options = unreal.FbxImportUI()
        options.set_editor_property("skeleton", skeleton.get_editor_property("skeleton") if isinstance(skeleton, unreal.SkeletalMesh) else skeleton)
        options.set_editor_property("import_mesh", True)
        options.set_editor_property("import_as_skeletal", True)
        options.set_editor_property("import_animations", True)
        task.set_editor_property("options", options)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return {"assets": describe(step["dest"])}


for step in job["steps"]:
    entry = dict(step)
    try:
        entry["result"] = do_import(step)
    except Exception:
        entry["error"] = traceback.format_exc()
    report["steps"].append(entry)
    with open(job["report"], "w", encoding="utf-8") as fh:  # a cada passo: se a Unreal cair, fica o que deu
        json.dump(report, fh, indent=1, ensure_ascii=False)
