"""Encerrar um personagem: as prévias viram um resultado só, com atalho fora da pasta do projeto.

Monta um acervo descartável (PONTE_DATA) com o boneco de teste e duas animações de
referência, aplica, reprova uma prévia, encerra e confere:

- antes de encerrar não existe resultado, e a prévia não traz arquivo para a engine;
- o GLB, o FBX e o BLEND do resultado têm um clipe por prévia não reprovada, com o nome e a
  duração dela;
- cada clipe do GLB tem o mesmo movimento da prévia de onde veio;
- o atalho fica fora da pasta do projeto e aponta para o resultado;
- mexer no projeto depois marca o resultado como desatualizado; renomear leva o atalho junto;
  reabrir e apagar tiram o resultado e o atalho.

Não usa o Kimodo nem toca no acervo de verdade. Com --keep, o acervo fica na pasta dada (com o
personagem encerrado), para abrir na interface: PONTE_DATA=<pasta>\\data uv run ponte serve --port 8766

    uv run python tests/check_close.py [--keep <pasta>]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
WALK = ROOT / "tests" / "fixtures" / "kimodo_walk_forward.bvh"


def shorter_bvh(source: Path, target: Path, frames: int) -> None:
    """Os primeiros quadros de um BVH: outra animação no mesmo esqueleto, com outra duração."""
    head, _, motion = source.read_text(encoding="utf-8").partition("MOTION")
    lines = motion.strip().splitlines()
    target.write_text(f"{head}MOTION\nFrames: {frames}\n{lines[1]}\n" + "\n".join(lines[2 : 2 + frames]) + "\n", encoding="utf-8")


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    bin_start = 20 + json_len
    return json.loads(data[20:bin_start]), data[bin_start + 8 : bin_start + 8 + struct.unpack_from("<I", data, bin_start)[0]]


def accessor(gltf: dict, blob: bytes, index: int) -> list[tuple[float, ...]]:
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    size = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or 4 * size
    return [struct.unpack_from(f"<{size}f", blob, start + i * stride) for i in range(acc["count"])]


def channel(gltf: dict, blob: bytes, animation: dict, bone: str, path: str) -> tuple[list, list] | None:
    """(tempos, valores) do canal ``path`` do osso ``bone`` numa animação do GLB."""
    for ch in animation["channels"]:
        if gltf["nodes"][ch["target"]["node"]].get("name") == bone and ch["target"]["path"] == path:
            sampler = animation["samplers"][ch["sampler"]]
            return accessor(gltf, blob, sampler["input"]), accessor(gltf, blob, sampler["output"])
    return None


def largest_gap(a: tuple[list, list], b: tuple[list, list]) -> float:
    if len(a[0]) != len(b[0]):
        return float("inf")
    return max((abs(x - y) for rows in zip(a[0] + a[1], b[0] + b[1]) for x, y in zip(*rows)), default=0.0)


def shortcut_target(link: Path) -> str:
    command = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; (New-Object -ComObject WScript.Shell).CreateShortcut($env:PONTE_LNK).TargetPath"
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], env={**os.environ, "PONTE_LNK": str(link)}, capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=Path, help="deixa o acervo de teste nesta pasta, com o personagem encerrado")
    args = ap.parse_args()
    work = args.keep.resolve() if args.keep else Path(tempfile.mkdtemp(prefix="ponte-encerrar-"))
    if args.keep:
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    os.environ["PONTE_DATA"] = str(work / "data")

    from ponte import blender, jobs, pipeline, shortcuts, store

    problems: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    def step(text: str) -> None:
        print(f"  · {text}", flush=True)

    def same_motion(asset_id: str, final: dict, previews: list[dict]) -> dict:
        """Cada clipe do GLB do resultado tem de ter o movimento da prévia de onde veio. Devolve o GLB."""
        gltf, blob = read_glb(store.final_folder(asset_id) / final["files"]["glb"])
        clips = {a["name"]: a for a in gltf.get("animations", [])}
        expect(sorted(clips) == sorted(c["name"] for c in final["clips"]), f"clipes no GLB: {sorted(clips)}")
        for preview, clip in zip(previews, final["clips"]):
            expect(clip["frames"] == preview["stats"]["frames"], f"{clip['name']}: {clip['frames']} quadros, a prévia tem {preview['stats']['frames']}")
            if clip["name"] not in clips:
                continue
            source, source_blob = read_glb(store.folder("result", preview["id"]) / "result.glb")
            for bone, path in (("mixamorig:Hips", "translation"), ("mixamorig:Hips", "rotation"), ("mixamorig:LeftArm", "rotation"), ("mixamorig:RightUpLeg", "rotation")):
                ours = channel(gltf, blob, clips[clip["name"]], bone, path)
                theirs = channel(source, source_blob, source["animations"][0], bone, path)
                if ours is None or theirs is None:
                    problems.append(f"{clip['name']}: canal {bone}/{path} ausente ({'resultado' if ours is None else 'prévia'})")
                elif largest_gap(ours, theirs) > 1e-4:
                    problems.append(f"{clip['name']}: {bone}/{path} difere da prévia em {largest_gap(ours, theirs):.5f}")
        return gltf

    try:
        rig = work / "boneco.fbx"
        blender.run_script("make_test_rig.py", ["--out", rig, "--pose", "A"], rig.with_suffix(".make.json"))
        asset_id = pipeline.add_asset(rig, "Boneco Ação", step)["id"]
        # Uma arma na mão: o acessório é do personagem e tem de sair no resultado também.
        prop_file = work / "fuzil.glb"
        blender.run_script("make_test_prop.py", ["--out", prop_file], prop_file.with_suffix(".make.json"))
        prop, prop_target = pipeline.create_prop(asset_id, prop_file.name)
        shutil.copy2(prop_file, prop_target)
        pipeline.convert_prop(asset_id, prop["id"], step)
        pipeline.place_prop(asset_id, prop["id"], "mixamorig:RightHand", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0.03, 0.09, -0.04, 1])
        shorter_bvh(WALK, work / "curta.bvh", 40)
        walk = pipeline.import_motion(asset_id, WALK, "walk forward")["id"]
        short = pipeline.import_motion(asset_id, work / "curta.bvh", "short walk")["id"]
        previews = [
            pipeline.retarget(asset_id, walk, log=step),
            pipeline.retarget(asset_id, walk, in_place=True, log=step),
            pipeline.retarget(asset_id, short, log=step),
            pipeline.retarget(asset_id, short, in_place=True, log=step),
        ]
        store.set_review("result", previews[0]["id"], "aprovado")
        store.set_review("result", previews[3]["id"], "reprovado", "não gostei")
        project = store.project_folder(asset_id)

        expect(sorted(previews[0]["files"]) == ["blend", "glb"], f"a prévia não deveria trazer arquivo para a engine: {sorted(previews[0]['files'])}")
        expect((project / "previas" / previews[0]["id"] / "result.glb").is_file(), "a prévia não está em previas/ dentro do projeto")
        expect(not store.final_folder(asset_id).exists() and not store.SHORTCUTS.exists(), "antes de encerrar não deveria existir resultado nem atalho")
        expect(store.get("asset", asset_id).get("final") is None, "o personagem nasce sem resultado")

        job = jobs.create("retarget", "trabalho em andamento", {"asset_id": asset_id})
        expect([j["id"] for j in pipeline.active_jobs(asset_id)] == [job["id"]], "job em andamento do projeto não foi visto")
        jobs.update(job["id"], status="ok")
        expect(pipeline.active_jobs(asset_id) == [], "job terminado ainda conta como em andamento")

        final = pipeline.close_project(asset_id, step)["final"]
        folder = store.final_folder(asset_id)
        names = [clip["name"] for clip in final["clips"]]
        expect(names == ["walk_forward", "walk_forward_parado", "short_walk"], f"clipes do resultado: {names}")
        expect(final["rejected"] == [previews[3]["id"]], f"reprovadas de fora: {final['rejected']}")
        expect(final["files"] == {"glb": "boneco-acao.glb", "fbx": "boneco-acao.fbx", "blend": "boneco-acao.blend"}, f"arquivos: {final['files']}")
        expect(sorted(p.name for p in folder.iterdir()) == sorted(final["files"].values()), f"na pasta do resultado: {sorted(p.name for p in folder.iterdir())}")
        expect(folder.parent == project, "o resultado deveria ficar dentro do projeto")

        # O GLB: um clipe por prévia, com o mesmo movimento dela, e a arma presa à mão.
        gltf = same_motion(asset_id, final, previews[:3])
        hand = next((n for n in gltf["nodes"] if n.get("name") == "mixamorig:RightHand"), {})
        expect(any(gltf["nodes"][i].get("name") == f"PROP_{prop['id']}" for i in hand.get("children", [])), "a arma não está presa à mão no GLB do resultado")
        # No FBX a arma só fica presa ao osso se o suporte dela (um Empty) for junto; sem ele ela sai solta na raiz.
        expect(f"PROP_{prop['id']}".encode() in (folder / final["files"]["fbx"]).read_bytes(), "o FBX do resultado saiu sem o suporte que prende a arma ao osso")

        # O FBX e o BLEND, reabertos no Blender: os mesmos clipes.
        for ext in ("fbx", "blend"):
            out = work / f"confere-{ext}"
            report = blender.run_script("inspect_asset.py", ["--input", folder / final["files"][ext], "--out-dir", out, "--mapping", out / "mapping.json"], out / "report.json")
            found = report["animations"]
            for clip in final["clips"]:
                match = [a for a in found if a["name"].split("|")[-1] == clip["name"]]
                expect(len(match) == 1 and abs(match[0]["frames"] - clip["frames"]) <= 1, f"{ext.upper()}: clipe {clip['name']} ({clip['frames']} quadros) não bate com {found}")
            expect(len(found) == len(names), f"{ext.upper()}: {len(found)} animação(ões), esperava {len(names)}: {[a['name'] for a in found]}")

        # O atalho: fora da pasta do projeto, apontando para o resultado.
        link = store.SHORTCUTS / final["shortcut"]
        expect(final["shortcut"] == "Boneco Ação.lnk" and link.is_file(), f"atalho: {final['shortcut']}")
        expect(project not in link.parents and store.PROJECTS not in link.parents, "o atalho deveria ficar fora das pastas dos projetos")
        expect(Path(shortcut_target(link)) == folder, f"o atalho aponta para {shortcut_target(link)!r}")
        shortcuts.create(work / "nomes" / "キャラ ✓.lnk", folder)
        expect((work / "nomes" / "キャラ ✓.lnk").is_file(), "atalho com nome fora do alfabeto do sistema não foi criado")

        # O que a interface recebe, e o aviso de desatualizado.
        from ponte import server

        def shown() -> dict:
            return next(a for a in server.state()["assets"] if a["id"] == asset_id)["final"]

        expect(shown()["stale"] is False and shown()["files_base"] == f"/files/projects/{asset_id}/resultado", f"estado do resultado: {shown()['stale']}, {shown()['files_base']}")
        store.set_review("result", previews[1]["id"], "reprovado")
        expect(shown()["stale"] is True, "reprovar uma prévia que entrou deveria marcar o resultado como desatualizado")
        store.set_review("result", previews[1]["id"], "pendente")
        expect(shown()["stale"] is False, "voltar a prévia ao que era deveria tirar o aviso")
        pipeline.place_prop(asset_id, prop["id"], "mixamorig:LeftHand", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
        expect(shown()["stale"] is True, "mudar a arma de mão deveria marcar o resultado como desatualizado")
        pipeline.place_prop(asset_id, prop["id"], "mixamorig:RightHand", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0.03, 0.09, -0.04, 1])

        pipeline.rename_asset(asset_id, "Herói")
        renamed = store.get("asset", asset_id)["final"]["shortcut"]
        expect(renamed == "Herói.lnk" and (store.SHORTCUTS / renamed).is_file() and not link.exists(), f"renomear o projeto deveria levar o atalho: {renamed}")

        # Outro projeto, cuja fonte é um .blend (como todo personagem rigado aqui) e com o mesmo nome do primeiro.
        rig_blend = work / "rigado.blend"
        blender.run_script("make_test_rig.py", ["--out", rig_blend, "--pose", "A", "--fbx-like"], rig_blend.with_suffix(".make.json"))
        other = pipeline.add_asset(rig_blend, "Herói", step)["id"]
        other_preview = pipeline.retarget(other, pipeline.import_motion(other, work / "curta.bvh", "short walk")["id"], log=step)
        other_final = pipeline.close_project(other, step)["final"]
        same_motion(other, other_final, [other_preview])
        expect(store.final_folder(other) != folder and (store.final_folder(other) / "heroi.fbx").is_file(), "o resultado do segundo projeto deveria ficar na pasta dele")
        expect(
            other_final["shortcut"] == f"Herói ({other.rsplit('-', 1)[-1]}).lnk" and (store.SHORTCUTS / other_final["shortcut"]).is_file() and (store.SHORTCUTS / renamed).is_file(),
            f"dois personagens com o mesmo nome deveriam ter um atalho cada: {renamed!r} e {other_final['shortcut']!r}",
        )
        expect(not shown().get("stale") and len(store.list_all("result", asset_id)) == 4, "mexer num projeto não pode respingar no outro")

        if args.keep:
            print(f"  acervo mantido em {work / 'data'} (projeto {asset_id})")
        else:
            pipeline.reopen_project(asset_id)
            expect(store.get("asset", asset_id).get("final") is None and not folder.exists() and not (store.SHORTCUTS / renamed).exists(), "reabrir deveria tirar o resultado e o atalho")
            expect(len(store.list_all("result", asset_id)) == 4, "reabrir não pode mexer nas prévias")
            again = pipeline.close_project(asset_id)["final"]
            pipeline.delete("asset", asset_id)
            expect(not project.exists() and not (store.SHORTCUTS / again["shortcut"]).exists(), "apagar o projeto deveria levar o atalho do resultado")
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(("FALHA " + "; ".join(problems)) if problems else "ok    encerrar: resultado único com as prévias, atalho fora do projeto")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
